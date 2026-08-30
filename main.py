"""
APF – Assistente Pessoal Financeiro
Serviço único FastAPI (chat + EPC + LLM + decisão + notificações)

Melhorias v2:
- Intent mais preciso (regex prioritário, fuzzy só como fallback fraco)
- Cards só quando o intent e o contexto justificam
- Comparador de pagamento interativo (selecionável no app)
- Mais grounding e boletos realistas
"""
import os
import re
from datetime import date, timedelta
from typing import Optional, Dict, Any, List

from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect, Depends, Request, HTTPException,
    UploadFile, File,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from dotenv import load_dotenv
from fuzzywuzzy import fuzz

from database import init_db, get_session, AsyncSessionLocal
from models import (
    User,
    Transaction,
    Pattern,
    Conversation,
    NotificationLog,
    PixAutomatico,
    BoletoPago,
)
from llm import call_groq, validate_grounding
from epc import run_epc
from decision import check_suitability_gate, comparar_formas_pagamento, get_perfil
from transfers import (
    detect_transfer_intent,
    parse_transfer,
    evaluate_security,
    list_known_favorecidos,
    list_recent_contacts,
    compute_saldo,
    execute_transfer,
    get_pending,
    set_pending,
    clear_pending,
    clarify_message,
    confirm_prompt,
    TransferDraft,
    open_boletos,
    configure_pix_automatico,
    list_pix_automaticos,
    mute_category,
    hydrate_flow_state,
    persist_flow_state,
    get_scanned_boleto,
)
from proactive import run_proactive_scan
from document_intelligence import scan_boleto
from telegram_integration import (
    configure_webhook,
    validate_webhook_secret,
    consume_continuation,
    telegram_payload,
    send_message as send_telegram_message,
    create_link_code,
    link_chat,
    resolve_user,
)

load_dotenv()

app = FastAPI(
    title="APF – Assistente Pessoal Financeiro",
    description="Protótipo Itaú Inovacamp | Dados sintéticos | Groq LLM",
    version="0.6.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Intent classification (preciso) ----------
# Ordem importa: padrões mais específicos primeiro.
INTENT_PATTERNS: Dict[str, List[str]] = {
    "seguranca": [
        r"golpe", r"fraude", r"at[ií]pico", r"seguran[cç]a",
    ],
    "transferir": [
        r"\bpix\b", r"\bted\b", r"transferir", r"enviar\s+dinheiro",
        r"fazer\s+(um\s+)?pix", r"enviar\s+(um\s+)?pix",
        r"manda[r]?\s+", r"quero\s+(fazer|enviar|mandar)",
    ],
    "padroes": [
        r"padr[aã]o", r"padr[oõ]es", r"recorrente", r"gasto\s+fixo",
        r"o\s+que\s+eu\s+pago", r"todo\s+m[eê]s", r"assinatura",
        r"detectou", r"antecip", r"pix\s+autom[aá]tico",
        r"meus\s+padr",
    ],
    "comparar": [
        r"comparar", r"melhor\s+forma", r"qual\s+(a\s+)?melhor",
        r"d[eé]bito\s+ou\s+cr[eé]dito", r"pix\s+ou\s+boleto",
        r"forma\s+de\s+pag",
    ],
    "pagar": [
        r"pagar", r"boleto", r"contas?\s+(pra|para|a)\s+pagar",
        r"que\s+contas", r"contas?\s+em\s+aberto",
        r"sabesp", r"enel", r"vivo",
    ],
    "investir": [
        r"investir", r"investimento", r"aplicar", r"rendimento",
        r"\bcdb\b", r"tesouro", r"poupan[cç]a", r"saldo\s+ocioso",
        r"dinheiro\s+parado", r"guard(?:ar|o|e|a)\b",
        r"(?:todo|restante|resto)\s+(?:do\s+)?saldo",
    ],
    "saldo": [
        r"\bsaldo\b", r"quanto\s+tenho", r"meu\s+dinheiro",
        r"dispon[ií]vel", r"quanto\s+tem",
    ],
    "extrato": [
        r"extrato", r"transa[cç][oõ]es", r"[uú]ltimas\s+movimenta",
        r"hist[oó]rico",
    ],
    "ajuda": [
        r"ajuda", r"o\s+que\s+voc[eê]\s+faz", r"como\s+funciona",
        r"o\s+que\s+consegue",
    ],
}


def classify_intent(text: str, user_id: str = "demo") -> str:
    text_l = text.lower().strip()

    # Continuação de transferência pendente (ex.: "150 pro João")
    pending = get_pending(user_id)
    if pending and pending.missing:
        if detect_transfer_intent(text) or re.search(r"\d", text_l) or len(text_l) > 2:
            return "transferir"

    if detect_transfer_intent(text):
        return "transferir"

    # 1) Match regex direto (prioridade)
    for intent, patterns in INTENT_PATTERNS.items():
        for p in patterns:
            if re.search(p, text_l):
                return intent

    # 2) Fuzzy fraco só se score bem alto
    best_score = 0
    best_intent = "geral"
    for intent, patterns in INTENT_PATTERNS.items():
        for p in patterns:
            plain = re.sub(r"[\\^$.*+?()[\]{}|]", " ", p)
            plain = re.sub(r"\s+", " ", plain).strip()
            if len(plain) < 4:
                continue
            score = fuzz.partial_ratio(plain, text_l)
            if score > best_score and score >= 85:
                best_score = score
                best_intent = intent
    return best_intent


def _fmt_brl(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _extract_valor(text: str, default: float = 187.40) -> float:
    m = re.search(r"R?\$?\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?|\d+[.,]?\d*)", text)
    if not m:
        return default
    raw = m.group(1).replace(".", "").replace(",", ".") if m.group(1).count(",") == 1 and m.group(1).count(".") >= 1 else m.group(1).replace(",", ".")
    # handle 2.500 -> 2500
    if re.match(r"^\d{1,3}\.\d{3}$", m.group(1)):
        raw = m.group(1).replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return default


def _resolve_investment_amount(text: str, saldo_disponivel: float) -> Dict[str, Any]:
    """Interpreta o valor solicitado sem confundi-lo com a reserva sugerida.

    Pedidos explícitos sempre prevalecem. Na ausência deles, a recomendação
    preserva R$ 2.000,00; se não houver excedente, nenhuma quantia é inventada.
    """
    text_l = text.lower().strip()
    saldo = max(0.0, round(float(saldo_disponivel or 0), 2))
    all_balance = bool(re.search(
        r"\b(?:todo|tudo|restante|resto)\b.*\b(?:saldo|dinheiro)\b|"
        r"\b(?:saldo|dinheiro)\b.*\b(?:todo|tudo|restante|resto)\b",
        text_l,
    ))
    if all_balance:
        return {"valor": saldo, "origem": "saldo_integral", "explicito": True}

    number = re.search(
        r"(?:r\$\s*)?(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
        r"\s*(mil)?\b",
        text_l,
    )
    if number:
        raw = number.group(1)
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d{1,3}\.\d{3}", raw):
            raw = raw.replace(".", "")
        valor = float(raw) * (1000 if number.group(2) else 1)
        return {"valor": round(valor, 2), "origem": "valor_informado", "explicito": True}

    excedente = max(0.0, round(saldo - 2000.0, 2))
    return {
        "valor": excedente if excedente > 0 else None,
        "origem": "excedente_sugerido",
        "explicito": False,
    }


# ---------- Grounding ----------
async def get_grounding_data(session: AsyncSession, user_id: str, intent: str) -> Dict[str, Any]:
    grounding: Dict[str, Any] = {
        "_source": "sintético",
        "_disclaimer": "Dados gerados para demonstração. Em produção, viriam das APIs Itaú.",
    }

    saldo_disponivel = await compute_saldo(session, user_id)
    grounding["saldo"] = {
        "disponivel": saldo_disponivel,
        "bloqueado": 0.00,
    }

    result = await session.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id)
        .order_by(Transaction.data.desc())
        .limit(10)
    )
    txs = result.scalars().all()
    grounding["ultimas_transacoes"] = [
        {
            "data": t.data.isoformat(),
            "descricao": t.descricao,
            "valor": t.valor,
            "tipo": t.tipo,
            "categoria": t.categoria,
        }
        for t in txs
    ]

    result = await session.execute(
        select(Pattern).where(Pattern.user_id == user_id)
    )
    patterns = result.scalars().all()
    grounding["padroes"] = [
        {
            "tipo": p.tipo,
            "descricao": p.descricao,
            "valor_medio": p.valor_medio,
            "frequencia": p.frequencia,
            "_metodo": p.metodo,
            **{
                key: value
                for key, value in (p.raw_data or {}).items()
                if key in {"favorecido", "categoria", "ultima_data"}
            },
        }
        for p in patterns
    ]

    grounding["boletos"] = await open_boletos(session, user_id)
    grounding["contatos_recentes"] = await list_recent_contacts(session, user_id)
    grounding["pix_automaticos"] = await list_pix_automaticos(session, user_id)

    perfil = await get_perfil(session, user_id)
    grounding["perfil_investidor"] = perfil

    # Resumo por categoria (últimos 30 dias) para grounding mais rico
    # Mantenha o parâmetro como ``date``. SQLite aceita também uma string ISO,
    # mas o PostgreSQL faz tipagem estrita e rejeita DATE >= VARCHAR.
    trinta = date.today() - timedelta(days=30)
    cat_q = await session.execute(
        select(Transaction.categoria, func.sum(Transaction.valor), func.count())
        .where(
            Transaction.user_id == user_id,
            Transaction.data >= trinta,
            Transaction.categoria != "renda",
        )
        .group_by(Transaction.categoria)
        .order_by(func.sum(Transaction.valor).desc())
    )
    grounding["gastos_por_categoria_30d"] = [
        {"categoria": r[0], "total": round(float(r[1] or 0), 2), "qtd": r[2]}
        for r in cat_q.fetchall()
    ]

    return grounding


# ---------- Process message ----------
async def process_message(
    session: AsyncSession,
    text: str,
    user_id: str = "demo",
    channel: str = "flutter",
) -> Dict[str, Any]:
    await hydrate_flow_state(session, user_id)
    intent = classify_intent(text, user_id)
    text_l = text.lower()

    # Cancelamento explícito
    if re.search(r"\b(cancela[r]?|desistir|deixa\s+pra\s+l[aá])\b", text_l):
        if get_pending(user_id):
            clear_pending(user_id)
            msg = "Transferência cancelada. Se quiser, é só pedir de novo."
            session.add(Conversation(user_id=user_id, channel=channel, role="user", content=text, intent="transferir"))
            session.add(Conversation(user_id=user_id, channel=channel, role="assistant", content=msg, intent="transferir"))
            await session.commit()
            return {
                "text": msg,
                "intent": "transferir",
                "channel": channel,
                "cards": [],
                "grounding_summary": {"_source": "sintético"},
            }

    # EPC só quando relevante
    if intent in ("padroes", "extrato"):
        try:
            await run_epc(session, user_id)
        except Exception as e:
            print(f"[epc] {e}")

    grounding = await get_grounding_data(session, user_id, intent)
    cards: List[Dict[str, Any]] = []

    result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.created_at.desc())
        .limit(6)
    )
    history_rows = result.scalars().all()[::-1]
    history = [{"role": r.role, "content": r.content} for r in history_rows]

    padroes = grounding.get("padroes") or []
    boletos = grounding.get("boletos") or []
    saldo = grounding.get("saldo") or {}

    # ---------- TRANSFERIR / PIX (transacional) ----------
    if intent == "transferir":
        pending = get_pending(user_id)
        draft = parse_transfer(text, user_id=user_id, base=pending)
        known = await list_known_favorecidos(session, user_id)
        draft = evaluate_security(draft, known)

        if draft.missing:
            set_pending(user_id, draft)
            safe = clarify_message(draft)
            contacts = grounding.get("contatos_recentes") or await list_recent_contacts(session, user_id)
            cards_miss = [{
                "type": "transfer_contacts",
                "title": "Contatos recentes",
                "data": {
                    "contatos": contacts,
                    "valor_sugerido": draft.valor,
                    "pending": draft.to_dict(),
                },
            }] if contacts else []
            session.add(Conversation(user_id=user_id, channel=channel, role="user", content=text, intent=intent))
            session.add(Conversation(user_id=user_id, channel=channel, role="assistant", content=safe, intent=intent))
            await session.commit()
            return {
                "text": safe,
                "intent": intent,
                "channel": channel,
                "cards": cards_miss,
                "grounding_summary": {
                    "saldo": grounding.get("saldo"),
                    "pending": draft.to_dict(),
                    "_source": "sintético",
                },
            }

        # Completo → card de confirmação (e segurança se preciso)
        set_pending(user_id, draft)
        safe = confirm_prompt(draft)
        contacts = grounding.get("contatos_recentes") or await list_recent_contacts(session, user_id)
        card_data = {
            "tipo": draft.tipo,
            "valor": draft.valor,
            "favorecido": draft.favorecido,
            "descricao": draft.descricao,
            "needs_security": draft.needs_security and not draft.security_passed,
            "chave_nova": draft.chave_nova,
            "saldo_disponivel": float(saldo.get("disponivel") or 0),
            "contatos_recentes": contacts,
            "editavel": True,
        }
        if draft.needs_security and not draft.security_passed:
            cards.append({
                "type": "security_check",
                "title": "Confirmação de segurança",
                "data": {
                    "mensagem": (
                        f"Valor de R$ {_fmt_brl(float(draft.valor))} para {draft.favorecido}. "
                        "Confirme se reconhece o destinatário antes de enviar."
                    ),
                    "valor": draft.valor,
                    "favorecido": draft.favorecido,
                    "acao_sugerida": "Confirmar identidade",
                    "acao_secundaria": "Cancelar",
                },
            })
        cards.append({
            "type": "transfer_confirm",
            "title": f"{'Pix' if draft.tipo == 'pix' else draft.tipo.upper()} — confirmar envio",
            "data": card_data,
        })
        session.add(Conversation(user_id=user_id, channel=channel, role="user", content=text, intent=intent))
        session.add(Conversation(user_id=user_id, channel=channel, role="assistant", content=safe, intent=intent))
        await session.commit()
        return {
            "text": safe,
            "intent": intent,
            "channel": channel,
            "cards": cards,
            "grounding_summary": {
                "saldo": grounding.get("saldo"),
                "_source": "sintético",
            },
        }

    # Demais intents usam LLM
    raw = await call_groq(text, intent, grounding, history)
    safe = validate_grounding(raw, grounding)

    # --- PADRÕES ---
    if intent == "padroes":
        if not padroes:
            safe = (
                "Ainda não encontrei padrões recorrentes claros no seu extrato. "
                "Quando houver 3 ou mais ciclos do mesmo Pix ou valor, consigo detectar automaticamente."
            )
        else:
            linhas = []
            for p in padroes[:6]:
                linhas.append(
                    f"• {p.get('descricao')}: R$ {_fmt_brl(float(p.get('valor_medio') or 0))} "
                    f"({p.get('frequencia')}x) — agregação SQL"
                )
                cards.append({
                    "type": "pattern",
                    "title": p.get("descricao", "Padrão detectado"),
                    "data": {
                        "tipo": p.get("tipo"),
                        "descricao": p.get("descricao"),
                        "valor_medio": p.get("valor_medio"),
                        "frequencia": p.get("frequencia"),
                        "metodo": p.get("_metodo", "agregacao_sql"),
                        "nota": "Detectado por agregação SQL (não clustering).",
                        "acao_sugerida": "Configurar Pix Automático"
                        if p.get("tipo") == "pix_recorrente"
                        else "Ver detalhes",
                        "favorecido": p.get("favorecido"),
                    },
                })
            safe = (
                "Encontrei estes padrões no seu histórico:\n\n"
                + "\n".join(linhas)
                + "\n\nPosso sugerir Pix Automático (mecanismo do Banco Central) para as recorrências de Pix."
            )
            pix_rec = next((p for p in padroes if p.get("tipo") == "pix_recorrente"), None)
            if pix_rec:
                cards.append({
                    "type": "proactive",
                    "title": "Sugestão EPC — Pix Automático",
                    "data": {
                        "mensagem": (
                            f"Você paga cerca de R$ {_fmt_brl(float(pix_rec.get('valor_medio') or 1500))} "
                            f"de forma recorrente ({pix_rec.get('frequencia')}x). "
                            "Quer configurar o Pix Automático para não esquecer o vencimento?"
                        ),
                        "categoria": "pix_recorrente",
                        "acao_sugerida": "Configurar Pix Automático",
                        "action": {
                            "type": "configure_pix_auto",
                            "favorecido": pix_rec.get("favorecido"),
                            "valor": pix_rec.get("valor_medio"),
                            "dia_mes": 10,
                        },
                    },
                })

    # --- COMPARAR (só comparador, sem misturar com boletos) ---
    elif intent == "comparar":
        valor = _extract_valor(text, 187.40)
        comparacao = comparar_formas_pagamento(
            valor, saldo_disponivel=float(saldo.get("disponivel") or 0)
        )
        safe = (
            f"Comparei as formas de pagamento para R$ {_fmt_brl(valor)}. "
            "O card mostra o impacto no saldo, na fatura e no limite. "
            "A recomendação usa as premissas explícitas do cenário sintético."
        )
        cards.append({
            "type": "payment_comparison",
            "title": f"Comparativo para R$ {_fmt_brl(valor)}",
            "data": comparacao,
        })

    # --- PAGAR (boletos + opcionalmente comparador se pedir valor) ---
    elif intent == "pagar":
        if boletos:
            lista = "\n".join(
                f"• {b['beneficiario']}: R$ {_fmt_brl(float(b['valor']))} (vence {b['vencimento']})"
                for b in boletos
            )
            safe = (
                f"Contas em aberto:\n{lista}\n\n"
                "Toque em Pagar no card para liquidar, ou peça para comparar formas de pagamento."
            )
            cards.append({
                "type": "bills",
                "title": "Contas a pagar",
                "data": {
                    "boletos": boletos,
                    "_source": "sintético",
                },
            })
            # Comparador só se o usuário citou valor ou "comparar" implícito
            if re.search(r"compar|melhor|forma", text_l) or _extract_valor(text, 0) > 0:
                valor = _extract_valor(text, float(boletos[0]["valor"]))
                cards.append({
                    "type": "payment_comparison",
                    "title": f"Comparativo para R$ {_fmt_brl(valor)}",
                    "data": comparar_formas_pagamento(valor),
                })
        else:
            safe = "Não há boletos em aberto neste momento."

    # --- INVESTIR ---
    elif intent == "investir":
        produto = "cdb_liquidez"
        if "tesouro" in text_l:
            produto = "tesouro_selic"
        elif "poupan" in text_l:
            produto = "poupanca"
        elif any(x in text_l for x in ("ação", "acoes", "ações", "cripto", "bitcoin", "multimercado", "coe")):
            produto = "acoes"
        gate = await check_suitability_gate(session, user_id, produto)
        if not gate.get("permitido"):
            safe = gate.get(
                "mensagem",
                "Esse produto não está disponível para o seu perfil neste protótipo. "
                "Só sugerimos CDB liquidez diária, poupança e Tesouro Selic.",
            )
            cards.append({
                "type": "suitability_blocked",
                "title": "Bloqueado pelo gate de suitability (CVM)",
                "data": gate if isinstance(gate, dict) else {"mensagem": safe},
            })
        else:
            saldo_disponivel = float(saldo.get("disponivel") or 0)
            amount = _resolve_investment_amount(text, saldo_disponivel)
            valor_sugerido = amount["valor"]
            if amount["origem"] == "saldo_integral":
                if not valor_sugerido:
                    safe = "Não há saldo disponível para aplicar neste momento."
                    valor_sugerido = None
                else:
                    safe = (
                        f"Você pediu para aplicar **todo o saldo disponível**, no valor de "
                        f"R$ {_fmt_brl(float(valor_sugerido))}.\n\n"
                        "- Saldo após a aplicação: **R$ 0,00**\n"
                        "- Confira o valor antes de confirmar."
                    )
            elif amount["origem"] == "valor_informado":
                valor = float(valor_sugerido or 0)
                if valor > saldo_disponivel:
                    safe = (
                        f"O valor solicitado, **R$ {_fmt_brl(valor)}**, supera o saldo "
                        f"disponível de **R$ {_fmt_brl(saldo_disponivel)}**.\n\n"
                        "Informe um valor menor para continuar."
                    )
                    valor_sugerido = None
                else:
                    safe = (
                        f"Você pediu uma aplicação de **R$ {_fmt_brl(valor)}** em "
                        f"{gate.get('produto')}.\n\n"
                        f"- Saldo após a aplicação: **R$ {_fmt_brl(saldo_disponivel - valor)}**\n"
                        "- Confira o valor antes de confirmar."
                    )
            elif valor_sugerido is None:
                safe = (
                    "Seu saldo disponível não possui valor acima da reserva de segurança "
                    "de **R$ 2.000,00**.\n\n"
                    "Por isso, não sugeri uma aplicação automática. Se quiser investir mesmo "
                    "assim, informe o valor exato ou peça para aplicar todo o saldo."
                )
            else:
                safe = (
                    f"Há **R$ {_fmt_brl(float(valor_sugerido))}** acima da reserva de "
                    "segurança de R$ 2.000,00.\n\n"
                    f"Sugestão alinhada ao seu perfil ({gate.get('perfil')}): "
                    f"{gate.get('produto')}. {gate.get('disclaimer', '')}"
                )
            cards.append({
                "type": "investment_suggestion",
                "title": gate.get("produto", produto),
                "data": {
                    "produto": gate.get("produto"),
                    "produto_id": produto,
                    "risco": gate.get("risco"),
                    "descricao": gate.get("descricao"),
                    "rendimento_estimado": gate.get("rendimento_estimado"),
                    "perfil": gate.get("perfil"),
                    "disclaimer": gate.get("disclaimer"),
                    "valor_sugerido": valor_sugerido,
                    "valor_origem": amount["origem"],
                },
            })

    # --- SEGURANÇA (consulta genérica; fluxo Pix já tem gate próprio) ---
    elif intent == "seguranca":
        safe = (
            "Posso ajudar a validar transferências atípicas. "
            "Se for enviar um Pix, diga o valor e o destinatário — "
            "eu verifico se o padrão é incomum antes de você confirmar."
        )

    # --- SALDO ---
    elif intent == "saldo":
        disp = float(saldo.get("disponivel") or 0)
        safe = (
            f"Seu saldo disponível é R$ {_fmt_brl(disp)}. "
            f"Há {len(boletos)} boleto(s) próximo(s) do vencimento. "
            "Quer ver padrões de gasto ou comparar formas de pagamento?"
        )
        cards.append({
            "type": "balance",
            "title": "Seu saldo",
            "data": {
                "disponivel": disp,
                "bloqueado": saldo.get("bloqueado", 0),
                "boletos": boletos,
                "_source": "sintético",
            },
        })
        # NÃO injeta pattern card no saldo (evita card indesejado)

    # --- EXTRATO ---
    elif intent == "extrato":
        txs = grounding.get("ultimas_transacoes") or []
        if txs:
            linhas = "\n".join(
                f"• {t['data']}: {t['descricao']} — R$ {_fmt_brl(float(t['valor']))}"
                for t in txs[:6]
            )
            safe = f"Últimas movimentações:\n{linhas}"
            cards.append({
                "type": "statement",
                "title": "Extrato recente",
                "data": {"transacoes": txs[:8], "_source": "sintético"},
            })
        else:
            safe = "Não há transações no período."

    # --- AJUDA ---
    elif intent == "ajuda":
        safe = (
            "Sou o Assistente Pessoal Financeiro do Itaú. Posso consultar saldo e extrato, "
            "detectar padrões, pagar boletos, enviar Pix/TED e sugerir investimentos "
            "alinhados ao seu perfil (suitability CVM).\n\n"
            "Exemplos: \"pix de 150 para João\", \"qual meu saldo?\", \"meus padrões\", "
            "\"que contas pagar?\", \"quero investir em CDB\"."
        )

    # geral: sem cards extras

    session.add(Conversation(user_id=user_id, channel=channel, role="user", content=text, intent=intent))
    session.add(Conversation(user_id=user_id, channel=channel, role="assistant", content=safe, intent=intent))
    await session.commit()

    return {
        "text": safe,
        "intent": intent,
        "channel": channel,
        "cards": cards,
        "grounding_summary": {
            "saldo": grounding.get("saldo"),
            "padroes_count": len(padroes),
            "_source": "sintético",
        },
    }


# ---------- Endpoints ----------
@app.on_event("startup")
async def startup():
    await init_db()
    if (os.getenv("AUTO_SEED_DEMO") or "false").lower() == "true":
        async with AsyncSessionLocal() as session:
            demo_exists = await session.get(User, "demo") is not None
        if not demo_exists:
            from seed import seed
            await seed()
            print("✅ Base sintética de demonstração criada.")
    print("✅ Banco inicializado.")
    if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("PUBLIC_BASE_URL"):
        try:
            result = await configure_webhook()
            print("✅ Webhook do Telegram configurado.", result.get("ok", False))
        except Exception as exc:
            # O backend deve continuar disponível mesmo se o Telegram estiver
            # temporariamente indisponível durante a inicialização.
            print(f"⚠️ Webhook do Telegram não configurado: {exc}")


@app.get("/")
async def root():
    return {
        "service": "APF – Assistente Pessoal Financeiro",
        "mode": "demo_sintetico",
        "version": "0.6.0",
        "docs": "/docs",
        "ws": "/ws",
    }


@app.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    print("WebSocket conectado")
    try:
        while True:
            data = await websocket.receive_json()
            text = data.get("text", "")
            user_id = data.get("user_id", "demo")
            # Ação interativa do card (confirmação de pagamento, etc.)
            action = data.get("action")
            if action:
                async with AsyncSessionLocal() as session:
                    await hydrate_flow_state(session, user_id)
                    response = await _handle_card_action(session, action, user_id)
                    await persist_flow_state(session, user_id, channel="flutter")
                    await session.commit()
                await websocket.send_json(response)
                continue

            async with AsyncSessionLocal() as session:
                response = await process_message(session, text, user_id, channel="flutter")
                await persist_flow_state(session, user_id, channel="flutter")
                await session.commit()

            await websocket.send_json(response)
    except WebSocketDisconnect:
        print("WebSocket desconectado")
    except Exception as e:
        print(f"Erro WS: {e}")
        try:
            await websocket.close()
        except Exception:
            pass


async def _handle_card_action(
    session: AsyncSession, action: Dict[str, Any], user_id: str
) -> Dict[str, Any]:
    """Processa ações dos cards interativos (Pix, boleto, etc.)."""
    kind = action.get("type", "")

    if kind == "resume_continuation":
        resumed = await consume_continuation(
            session, str(action.get("token") or ""), user_id
        )
        if not resumed:
            return {
                "text": "Este link expirou ou já foi utilizado. Volte ao Telegram e gere uma nova continuação.",
                "intent": "geral", "channel": "flutter", "cards": [],
                "grounding_summary": {"_source": "sintético"},
            }
        resumed_kind = resumed.get("type")
        if resumed_kind == "resume_pending_transfer":
            action = {"type": "update_transfer"}
            kind = "update_transfer"
        elif resumed_kind == "resume_bill":
            return await process_message(
                session, "Que contas tenho para pagar?", user_id, channel="flutter"
            )
        elif resumed_kind == "resume_comparison":
            return await process_message(
                session, f"Comparar pagamento de {resumed.get('valor') or 187.40}", user_id,
                channel="flutter",
            )
        elif resumed_kind == "resume_investment":
            return await process_message(
                session, f"Quero investir em {resumed.get('produto') or 'CDB'}", user_id,
                channel="flutter",
            )

    if kind == "execute_transfer":
        pending = get_pending(user_id)
        if not pending:
            return {
                "text": "Essa transferência expirou. Inicie um novo Pix para continuar com segurança.",
                "intent": "transferir", "channel": "flutter", "cards": [],
                "grounding_summary": {"_source": "sintético"},
            }
        if pending.needs_security and not pending.security_passed:
            return {
                "text": "Confirme a identidade do destinatário antes de enviar.",
                "intent": "transferir", "channel": "flutter",
                "cards": [{
                    "type": "security_check",
                    "title": "Confirmação de segurança",
                    "data": {
                        "mensagem": (
                            f"Valor de R$ {_fmt_brl(float(pending.valor or 0))} para "
                            f"{pending.favorecido}. Confirme se reconhece o destinatário."
                        ),
                        "acao_sugerida": "Confirmar no dispositivo",
                        "acao_secundaria": "Cancelar",
                    },
                }],
                "grounding_summary": {"_source": "sintético"},
            }
        # O rascunho mantido pelo servidor é a fonte de verdade. O cliente não pode
        # trocar valor, favorecido ou tipo no instante da execução.
        draft = pending
        if not draft.valor or not draft.favorecido:
            return {
                "text": "Não consegui concluir: faltam valor ou destinatário.",
                "intent": "transferir",
                "channel": "flutter",
                "cards": [],
                "grounding_summary": {"_source": "sintético"},
            }
        result = await execute_transfer(session, user_id, draft)
        if not result.get("ok"):
            if result.get("erro") == "saldo_insuficiente":
                msg = (
                    f"Saldo insuficiente. Disponível: R$ {_fmt_brl(float(result.get('saldo') or 0))}. "
                    f"Valor pedido: R$ {_fmt_brl(float(result.get('valor') or 0))}."
                )
            else:
                msg = "Não foi possível concluir a transferência."
            session.add(Conversation(
                user_id=user_id, channel="flutter", role="assistant",
                content=msg, intent="transferir",
            ))
            await session.commit()
            return {
                "text": msg,
                "intent": "transferir",
                "channel": "flutter",
                "cards": [],
                "grounding_summary": {"_source": "sintético"},
            }

        tipo_label = "Pix" if result["tipo"] == "pix" else result["tipo"].upper()
        msg = (
            f"{tipo_label} de R$ {_fmt_brl(result['valor'])} para {result['favorecido']} enviado. "
            f"Saldo atual: R$ {_fmt_brl(result['saldo_apos'])}."
        )
        session.add(Conversation(
            user_id=user_id, channel="flutter", role="assistant",
            content=msg, intent="transferir",
        ))
        await session.commit()
        return {
            "text": msg,
            "intent": "transferir",
            "channel": "flutter",
            "cards": [{
                "type": "transfer_receipt",
                "title": f"{tipo_label} enviado",
                "data": {
                    "tipo": result["tipo"],
                    "valor": result["valor"],
                    "favorecido": result["favorecido"],
                    "descricao": result["descricao"],
                    "data": result["data"],
                    "transaction_id": result["transaction_id"],
                    "saldo_apos": result["saldo_apos"],
                    "status": "enviado",
                    "comprovante_texto": result.get("comprovante_texto"),
                },
            }],
            "grounding_summary": {
                "saldo": {"disponivel": result["saldo_apos"]},
                "_source": "sintético",
            },
        }

    if kind == "cancel_transfer":
        clear_pending(user_id)
        msg = "Transferência cancelada."
        session.add(Conversation(
            user_id=user_id, channel="flutter", role="assistant",
            content=msg, intent="transferir",
        ))
        await session.commit()
        return {
            "text": msg,
            "intent": "transferir",
            "channel": "flutter",
            "cards": [],
            "grounding_summary": {"_source": "sintético"},
        }

    if kind == "security_pass":
        pending = get_pending(user_id)
        if pending:
            pending.security_passed = True
            pending.needs_security = False
            set_pending(user_id, pending)
            msg = (
                f"Identidade confirmada. Pode confirmar o envio de "
                f"R$ {_fmt_brl(float(pending.valor or 0))} para {pending.favorecido}."
            )
            card_data = {
                "tipo": pending.tipo,
                "valor": pending.valor,
                "favorecido": pending.favorecido,
                "descricao": pending.descricao,
                "needs_security": False,
                "saldo_disponivel": await compute_saldo(session, user_id),
            }
            session.add(Conversation(
                user_id=user_id, channel="flutter", role="assistant",
                content=msg, intent="transferir",
            ))
            await session.commit()
            return {
                "text": msg,
                "intent": "transferir",
                "channel": "flutter",
                "cards": [{
                    "type": "transfer_confirm",
                    "title": f"{'Pix' if pending.tipo == 'pix' else pending.tipo.upper()} — confirmar envio",
                    "data": card_data,
                }],
                "grounding_summary": {"_source": "sintético"},
            }
        return {
            "text": "Identidade confirmada.",
            "intent": "transferir",
            "channel": "flutter",
            "cards": [],
            "grounding_summary": {"_source": "sintético"},
        }

    if kind == "confirm_payment":
        forma = action.get("forma", "Pix")
        boleto_id = action.get("boleto_id")
        if not boleto_id:
            valor = float(action.get("valor") or 0)
            if valor <= 0:
                return {
                    "text": "Informe um valor válido para continuar.",
                    "intent": "comparar", "channel": "flutter", "cards": [],
                    "grounding_summary": {"_source": "sintético"},
                }
            tipo = "pix" if str(forma).lower() == "pix" else "ted"
            draft = TransferDraft(tipo=tipo, valor=valor, missing=["favorecido"])
            set_pending(user_id, draft)
            contacts = await list_recent_contacts(session, user_id)
            return {
                "text": (
                    f"{forma} selecionado para R$ {_fmt_brl(valor)}. "
                    "Agora escolha um contato ou diga para quem deseja pagar."
                ),
                "intent": "transferir", "channel": "flutter",
                "cards": [{
                    "type": "transfer_contacts",
                    "title": "Escolha o destinatário",
                    "data": {"contatos": contacts, "valor_sugerido": valor},
                }] if contacts else [],
                "grounding_summary": {"_source": "sintético"},
            }

        # Para boleto, valor e beneficiário sempre vêm do servidor.
        bills = await open_boletos(session, user_id)
        bill = next((item for item in bills if item["id"] == boleto_id), None)
        if not bill:
            bill = await get_scanned_boleto(session, user_id, boleto_id)
        if not bill:
            return {
                "text": "Esse boleto já foi pago ou não está mais disponível.",
                "intent": "pagar", "channel": "flutter", "cards": [],
                "grounding_summary": {"_source": "sintético"},
            }
        draft = TransferDraft(
            tipo="boleto",
            valor=float(bill["valor"]),
            favorecido=bill["beneficiario"],
            boleto_id=boleto_id,
            security_passed=True,
        )
        result = await execute_transfer(session, user_id, draft)
        if not result.get("ok"):
            if result.get("erro") == "saldo_insuficiente":
                msg = f"Saldo insuficiente. Disponível: R$ {_fmt_brl(float(result.get('saldo') or 0))}."
            else:
                msg = "Não foi possível concluir o pagamento."
            session.add(Conversation(
                user_id=user_id, channel="flutter", role="assistant",
                content=msg, intent="pagar",
            ))
            await session.commit()
            return {
                "text": msg,
                "intent": "pagar",
                "channel": "flutter",
                "cards": [],
                "grounding_summary": {"_source": "sintético"},
            }

        msg = (
            f"Pagamento de R$ {_fmt_brl(result['valor'])} via {forma} concluído"
            + (f" ({boleto_id})" if boleto_id else "")
            + f". Saldo atual: R$ {_fmt_brl(result['saldo_apos'])}."
        )
        session.add(Conversation(
            user_id=user_id, channel="flutter", role="assistant",
            content=msg, intent="pagar",
        ))
        await session.commit()
        return {
            "text": msg,
            "intent": "pagar",
            "channel": "flutter",
            "cards": [{
                "type": "transfer_receipt",
                "title": "Pagamento confirmado",
                "data": {
                    "tipo": result["tipo"],
                    "valor": result["valor"],
                    "favorecido": result["favorecido"],
                    "descricao": result["descricao"],
                    "data": result["data"],
                    "transaction_id": result["transaction_id"],
                    "saldo_apos": result["saldo_apos"],
                    "status": "pago",
                    "boleto_id": boleto_id,
                },
            }],
            "grounding_summary": {
                "saldo": {"disponivel": result["saldo_apos"]},
                "_source": "sintético",
            },
        }

    if kind == "configure_pix_auto":
        favorecido = str(action.get("favorecido") or "").strip()
        valor = float(action.get("valor") or 0)
        dia = int(action.get("dia_mes") or 10)
        if not favorecido or valor <= 0:
            return {
                "text": "Não foi possível configurar: faltam favorecido ou valor válido.",
                "intent": "padroes", "channel": "flutter", "cards": [],
                "grounding_summary": {"_source": "sintético"},
            }
        saved = await configure_pix_automatico(
            session, user_id, favorecido=favorecido, valor=valor or 0, dia_mes=dia,
        )
        msg = (
            f"Pix Automático configurado para {saved['favorecido']} "
            f"(R$ {_fmt_brl(float(saved['valor']))}) todo dia {saved['dia_mes']}. "
            "Você receberá um lembrete antes de cada débito."
        )
        session.add(Conversation(
            user_id=user_id, channel="flutter", role="assistant",
            content=msg, intent="padroes",
        ))
        await session.commit()
        return {
            "text": msg,
            "intent": "padroes",
            "channel": "flutter",
            "cards": [{
                "type": "pix_auto_configured",
                "title": "Pix Automático ativo",
                "data": saved,
            }],
            "grounding_summary": {"_source": "sintético"},
        }

    if kind == "apply_investment":
        produto = action.get("produto") or "CDB Liquidez Diária"
        produto_id = action.get("produto_id") or {
            "CDB Liquidez Diária": "cdb_liquidez",
            "Poupança": "poupanca",
            "Tesouro Selic": "tesouro_selic",
            "CDB Pós-fixado": "cdb_pos",
            "Fundos de Renda Fixa": "fundos_rf",
        }.get(produto)
        valor = float(action.get("valor") or 0)
        gate = await check_suitability_gate(session, user_id, produto_id or "produto_desconhecido")
        if valor <= 0 or not gate.get("permitido"):
            msg = gate.get("mensagem") or "Informe um valor válido para a aplicação."
            return {
                "text": msg, "intent": "investir", "channel": "flutter", "cards": [],
                "grounding_summary": {"_source": "sintético"},
            }
        draft = TransferDraft(
            tipo="investimento",
            valor=valor,
            favorecido=produto,
            descricao=f"Aplicação em {produto}",
            security_passed=True,
        )
        result = await execute_transfer(session, user_id, draft)
        if not result.get("ok"):
            if result.get("erro") == "saldo_insuficiente":
                msg = f"Saldo insuficiente. Disponível: R$ {_fmt_brl(float(result.get('saldo') or 0))}."
            else:
                msg = "Não foi possível concluir a aplicação."
            session.add(Conversation(
                user_id=user_id, channel="flutter", role="assistant",
                content=msg, intent="investir",
            ))
            await session.commit()
            return {"text": msg, "intent": "investir", "channel": "flutter", "cards": [], "grounding_summary": {"_source": "sintético"}}
        msg = (
            f"Aplicação de R$ {_fmt_brl(result['valor'])} em {produto} concluída. "
            f"Saldo atual: R$ {_fmt_brl(result['saldo_apos'])}. "
            "Projeção estimada. Rentabilidade passada não garante rentabilidade futura."
        )
        session.add(Conversation(
            user_id=user_id, channel="flutter", role="assistant",
            content=msg, intent="investir",
        ))
        await session.commit()
        return {
            "text": msg,
            "intent": "investir",
            "channel": "flutter",
            "cards": [{
                "type": "transfer_receipt",
                "title": "Aplicação confirmada",
                "data": {
                    "tipo": "investimento",
                    "valor": result["valor"],
                    "favorecido": produto,
                    "descricao": result["descricao"],
                    "data": result["data"],
                    "transaction_id": result["transaction_id"],
                    "saldo_apos": result["saldo_apos"],
                    "status": "aplicado",
                    "comprovante_texto": result.get("comprovante_texto"),
                },
            }],
            "grounding_summary": {"saldo": {"disponivel": result["saldo_apos"]}, "_source": "sintético"},
        }

    if kind == "request_investment_suggestion":
        return await process_message(
            session, "Quero investir em CDB com liquidez diária", user_id, channel="flutter"
        )

    if kind == "mute_suggestion":
        categoria = action.get("categoria") or "geral"
        await mute_category(session, user_id, categoria)
        msg = "Entendido. Não vou mais trazer essa sugestão."
        session.add(Conversation(
            user_id=user_id, channel="flutter", role="assistant",
            content=msg, intent="geral",
        ))
        await session.commit()
        return {
            "text": msg,
            "intent": "geral",
            "channel": "flutter",
            "cards": [],
            "muted": True,
            "categoria": categoria,
            "grounding_summary": {"_source": "sintético"},
        }

    if kind == "update_transfer":
        pending = get_pending(user_id) or TransferDraft()
        pending.security_passed = False
        if action.get("valor") is not None:
            pending.valor = float(action["valor"])
        if action.get("favorecido"):
            pending.favorecido = action["favorecido"]
        if action.get("tipo"):
            pending.tipo = action["tipo"]
        pending.missing = []
        if pending.valor is None:
            pending.missing.append("valor")
        if not pending.favorecido:
            pending.missing.append("favorecido")
        known = await list_known_favorecidos(session, user_id)
        pending = evaluate_security(pending, known)
        set_pending(user_id, pending)
        contacts = await list_recent_contacts(session, user_id)
        saldo = await compute_saldo(session, user_id)
        msg = confirm_prompt(pending)
        return {
            "text": msg,
            "intent": "transferir",
            "channel": "flutter",
            "cards": [{
                "type": "transfer_confirm",
                "title": f"{'Pix' if pending.tipo == 'pix' else pending.tipo.upper()} — confirmar envio",
                "data": {
                    "tipo": pending.tipo,
                    "valor": pending.valor,
                    "favorecido": pending.favorecido,
                    "descricao": pending.descricao,
                    "needs_security": pending.needs_security and not pending.security_passed,
                    "saldo_disponivel": saldo,
                    "contatos_recentes": contacts,
                    "editavel": True,
                },
            }],
            "grounding_summary": {"_source": "sintético"},
        }

    if kind == "select_contact":
        pending = get_pending(user_id) or TransferDraft()
        pending.security_passed = False
        pending.favorecido = action.get("favorecido") or pending.favorecido
        if action.get("valor") is not None:
            pending.valor = float(action["valor"])
        elif pending.valor is None and action.get("ultimo_valor") is not None:
            pending.valor = float(action["ultimo_valor"])
        pending.missing = []
        if pending.valor is None:
            pending.missing.append("valor")
        if not pending.favorecido:
            pending.missing.append("favorecido")
        if pending.missing:
            set_pending(user_id, pending)
            return {
                "text": clarify_message(pending),
                "intent": "transferir",
                "channel": "flutter",
                "cards": [],
                "grounding_summary": {"_source": "sintético"},
            }
        known = await list_known_favorecidos(session, user_id)
        pending = evaluate_security(pending, known)
        set_pending(user_id, pending)
        contacts = await list_recent_contacts(session, user_id)
        saldo = await compute_saldo(session, user_id)
        msg = confirm_prompt(pending)
        cards = []
        if pending.needs_security and not pending.security_passed:
            cards.append({
                "type": "security_check",
                "title": "Confirmação de segurança",
                "data": {
                    "mensagem": f"Valor de R$ {_fmt_brl(float(pending.valor))} para {pending.favorecido}. Confirme se reconhece o destinatário.",
                    "valor": pending.valor,
                    "favorecido": pending.favorecido,
                    "acao_sugerida": "Confirmar identidade",
                    "acao_secundaria": "Cancelar",
                },
            })
        cards.append({
            "type": "transfer_confirm",
            "title": "Pix — confirmar envio",
            "data": {
                "tipo": pending.tipo or "pix",
                "valor": pending.valor,
                "favorecido": pending.favorecido,
                "needs_security": pending.needs_security and not pending.security_passed,
                "saldo_disponivel": saldo,
                "contatos_recentes": contacts,
                "editavel": True,
            },
        })
        return {
            "text": msg,
            "intent": "transferir",
            "channel": "flutter",
            "cards": cards,
            "grounding_summary": {"_source": "sintético"},
        }

    return {
        "text": "Ação registrada.",
        "intent": "geral",
        "channel": "flutter",
        "cards": [],
        "grounding_summary": {"_source": "sintético"},
    }


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if not validate_webhook_secret(
        request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    ):
        raise HTTPException(status_code=401, detail="Webhook secret inválido")
    body = await request.json()
    message = body.get("message") or body.get("edited_message")
    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    async with AsyncSessionLocal() as session:
        start_match = re.fullmatch(r"/start(?:@\w+)?\s+([A-Za-z0-9_-]+)", text.strip())
        if start_match:
            linked_user = await link_chat(session, chat_id, start_match.group(1))
            payload = {
                "text": (
                    "Telegram conectado ao APF. Você já pode consultar e iniciar jornadas por aqui; "
                    "qualquer confirmação financeira continuará no app."
                    if linked_user else
                    "Este código de vínculo expirou ou já foi usado. Gere um novo código no app."
                )
            }
            sent = await send_telegram_message(chat_id, payload)
            return {"ok": True, "sent": sent, "linked": bool(linked_user)}

        user_id = await resolve_user(session, chat_id)
        if not user_id:
            payload = {
                "text": "Abra o app APF e gere um código para conectar este Telegram com segurança."
            }
            sent = await send_telegram_message(chat_id, payload)
            return {"ok": True, "sent": sent, "linked": False}
        response = await process_message(session, text, user_id, channel="telegram")
        await persist_flow_state(session, user_id, channel="telegram")
        payload = await telegram_payload(session, response, user_id)
        await session.commit()

    sent = False
    try:
        sent = await send_telegram_message(chat_id, payload)
    except Exception as e:
        print(f"[Telegram] envio falhou: {e}")

    print(f"[Telegram] chat={chat_id} sent={sent} → {payload['text'][:80]}...")
    return {"ok": True, "sent": sent, "chat_id": chat_id}


@app.get("/continue/{token}", response_class=HTMLResponse)
async def continue_in_app(token: str):
    """Ponte HTTPS usada pelo botão do Telegram para abrir o app."""
    safe_token = re.sub(r"[^A-Za-z0-9_-]", "", token)
    deep_link = f"apf://continue?token={safe_token}"
    web_app = (os.getenv("APP_PUBLIC_URL") or "").rstrip("/")
    web_fallback = f"{web_app}/?token={safe_token}" if web_app else deep_link
    return HTMLResponse(
        "<!doctype html><html lang='pt-BR'><meta name='viewport' "
        "content='width=device-width,initial-scale=1'><title>Continuar no APF</title>"
        f"<script>location.href='{deep_link}';setTimeout(()=>location.href='{web_fallback}',900);</script>"
        "<body style='font-family:system-ui;padding:32px;text-align:center'>"
        "<h2>Continuando com segurança no app Itaú</h2>"
        f"<p><a href='{web_fallback}'>Continuar no aplicativo web</a></p>"
        "<p>Nenhuma transação é confirmada pelo Telegram.</p></body></html>"
    )


@app.post("/user/{user_id}/telegram/link-code")
async def telegram_link_code(
    user_id: str, session: AsyncSession = Depends(get_session)
):
    if not await session.get(User, user_id):
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    code = await create_link_code(session, user_id)
    bot_username = (os.getenv("TELEGRAM_BOT_USERNAME") or "seu_bot").lstrip("@")
    return {
        "code": code,
        "expires_in_seconds": 600,
        "telegram_url": f"https://t.me/{bot_username}?start={code}",
        "instructions": "Abra o link no Telegram. O código é de uso único.",
    }


@app.post("/user/{user_id}/boleto/scan")
async def scan_bill_image(
    user_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    try:
        data = await scan_boleto(
            session,
            user_id,
            await file.read(),
            file.content_type or "application/octet-stream",
            file.filename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    mode_note = (
        "Leitura feita pelo modelo multimodal. Revise os dados antes de pagar."
        if data["extraction_mode"] == "groq_vision"
        else "Modo demonstração: visão indisponível; dados de exemplo precisam ser revisados."
    )
    return {
        "text": f"Encontrei um boleto de {data['beneficiario']}. {mode_note}",
        "intent": "pagar",
        "cards": [{"type": "bill_scan", "title": "Revisar boleto", "data": data}],
        "grounding_summary": {"_source": data["source"]},
    }


@app.get("/user/{user_id}/dashboard")
async def dashboard(user_id: str, session: AsyncSession = Depends(get_session)):
    grounding = await get_grounding_data(session, user_id, "saldo")
    return {
        "user_id": user_id,
        "saldo": grounding["saldo"],
        "boletos": grounding["boletos"],
        "ultimas_transacoes": grounding["ultimas_transacoes"][:5],
        "gastos_por_categoria_30d": grounding.get("gastos_por_categoria_30d", []),
        "_source": "sintético",
        "_disclaimer": "Dados gerados para demonstração. Em produção, viriam das APIs Itaú.",
    }


@app.get("/user/{user_id}/patterns")
async def patterns(user_id: str, session: AsyncSession = Depends(get_session)):
    detected = await run_epc(session, user_id)
    return {
        "user_id": user_id,
        "patterns": detected,
        "_metodo": "agregacao_sql",
        "_nota": "Não utiliza clustering estatístico.",
        "_source": "sintético",
    }


@app.post("/user/{user_id}/consent")
async def update_consent(user_id: str, payload: dict, session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(404, "Usuário não encontrado")

    if "consent_padroes_pagamento" in payload:
        user.consent_padroes_pagamento = bool(payload["consent_padroes_pagamento"])
    if "consent_habitos_gasto" in payload:
        user.consent_habitos_gasto = bool(payload["consent_habitos_gasto"])
    if "consent_saldo_ocioso" in payload:
        user.consent_saldo_ocioso = bool(payload["consent_saldo_ocioso"])

    await session.commit()
    return {
        "ok": True,
        "consents": {
            "padroes_pagamento": user.consent_padroes_pagamento,
            "habitos_gasto": user.consent_habitos_gasto,
            "saldo_ocioso": user.consent_saldo_ocioso,
        },
    }


@app.delete("/user/{user_id}/data")
async def delete_user_data(user_id: str, session: AsyncSession = Depends(get_session)):
    await session.execute(Transaction.__table__.delete().where(Transaction.user_id == user_id))
    await session.execute(Pattern.__table__.delete().where(Pattern.user_id == user_id))
    await session.execute(Conversation.__table__.delete().where(Conversation.user_id == user_id))
    await session.execute(NotificationLog.__table__.delete().where(NotificationLog.user_id == user_id))
    await session.execute(PixAutomatico.__table__.delete().where(PixAutomatico.user_id == user_id))
    await session.execute(BoletoPago.__table__.delete().where(BoletoPago.user_id == user_id))
    user = await session.get(User, user_id)
    if user:
        user.consent_padroes_pagamento = False
        user.consent_habitos_gasto = False
        user.consent_saldo_ocioso = False
        user.muted_categories = {}
        user.notificacoes_hoje = 0
        user.ultima_notificacao_data = None
    clear_pending(user_id)
    await session.commit()
    return {
        "ok": True,
        "message": "Dados financeiros, padrões, conversas e preferências foram excluídos.",
    }


@app.post("/user/{user_id}/proactive/scan")
async def proactive_scan(user_id: str, session: AsyncSession = Depends(get_session)):
    results = await run_proactive_scan(session, user_id)
    return {"user_id": user_id, "results": results}


@app.get("/user/{user_id}/pix-automaticos")
async def pix_autos(user_id: str, session: AsyncSession = Depends(get_session)):
    return {"items": await list_pix_automaticos(session, user_id)}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": "demo_sintetico",
        "version": "0.5.0",
        "llm_model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        "llm_configured": bool(os.getenv("GROQ_API_KEY")),
    }

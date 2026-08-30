"""
Proatividade: verifica padrões / boletos / Pix Automático e dispara notificações
respeitando consent, mute, cap diário e janela.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from epc import run_epc
from notifications import send_proactive_notification
from transfers import open_boletos, list_pix_automaticos, is_muted, compute_saldo


def _fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


async def run_proactive_scan(session: AsyncSession, user_id: str = "demo") -> List[Dict[str, Any]]:
    """
    Gera candidatos a notificação e tenta enviar via regras de notifications.py.
    Retorna lista do que foi (ou não) enviado — útil para endpoint de demo.
    """
    results: List[Dict[str, Any]] = []

    # 1) Boletos próximos (7 dias, para materializar a antecipação na demo)
    boletos = await open_boletos(session, user_id)
    for b in boletos:
        try:
            venc = date.fromisoformat(b["vencimento"])
        except Exception:
            continue
        days = (venc - date.today()).days
        if 0 <= days <= 7:
            cat = "boletos"
            if await is_muted(session, user_id, cat) or await is_muted(session, user_id, "boletos"):
                results.append({"categoria": cat, "enviado": False, "motivo": "muted"})
                continue
            msg = (
                f"Lembrete: boleto {b['beneficiario']} de R$ {_fmt(float(b['valor']))} "
                f"vence em {days} dia(s) ({b['vencimento']}). Quer pagar agora?"
            )
            r = await send_proactive_notification(session, user_id, cat, msg)
            results.append({
                "categoria": cat,
                "mensagem": msg,
                "action": {
                    "type": "confirm_payment",
                    "forma": "Pix",
                    "boleto_id": b["id"],
                },
                "acao_sugerida": "Pagar agora",
                **r,
            })

    # 2) Pix Automático no dia
    autos = await list_pix_automaticos(session, user_id)
    today = date.today().day
    for a in autos:
        if a["dia_mes"] == today:
            cat = "pix_recorrente"
            if await is_muted(session, user_id, cat):
                results.append({"categoria": cat, "enviado": False, "motivo": "muted"})
                continue
            msg = (
                f"Pix Automático de R$ {_fmt(float(a['valor']))} para {a['favorecido']} "
                f"está programado para hoje (dia {a['dia_mes']})."
            )
            r = await send_proactive_notification(session, user_id, cat, msg)
            results.append({"categoria": cat, "mensagem": msg, **r})

    # 3) EPC — Pix recorrente sem automático configurado
    try:
        patterns = await run_epc(session, user_id)
    except Exception:
        patterns = []
    autos_fav = {a["favorecido"].lower() for a in autos}
    for p in patterns:
        if p.get("tipo") != "pix_recorrente":
            continue
        fav = (p.get("favorecido") or "").lower()
        if fav and fav in autos_fav:
            continue
        cat = "pix_recorrente"
        if await is_muted(session, user_id, cat):
            results.append({"categoria": cat, "enviado": False, "motivo": "muted"})
            continue
        msg = (
            f"Detectei Pix recorrente para {p.get('favorecido')} "
            f"(~R$ {_fmt(float(p.get('valor_medio') or 0))}). "
            "Quer configurar Pix Automático?"
        )
        r = await send_proactive_notification(session, user_id, cat, msg)
        results.append({
            "categoria": cat,
            "mensagem": msg,
            "action": {
                "type": "configure_pix_auto",
                "favorecido": p.get("favorecido"),
                "valor": p.get("valor_medio"),
                "dia_mes": 10,
            },
            "acao_sugerida": "Configurar Pix Automático",
            **r,
        })

    # 4) Saldo ocioso (se consent implícito via notificação investimento)
    saldo = await compute_saldo(session, user_id)
    if saldo > 5000:
        cat = "investimento"
        if await is_muted(session, user_id, cat):
            results.append({"categoria": cat, "enviado": False, "motivo": "muted"})
        else:
            ocioso = saldo - 2000
            msg = (
                f"Há cerca de R$ {_fmt(ocioso)} acima de uma reserva sugerida. "
                "Quer ver opções de CDB com liquidez diária?"
            )
            r = await send_proactive_notification(session, user_id, cat, msg)
            results.append({
                "categoria": cat,
                "mensagem": msg,
                "action": {"type": "request_investment_suggestion"},
                "acao_sugerida": "Ver opções",
                **r,
            })

    return results

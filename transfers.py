"""
Fluxo transacional: Pix / TED / boleto.
Parse NL, multi-turno, contatos, referências, execução.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, distinct, desc
from sqlalchemy.ext.asyncio import AsyncSession

from models import Transaction, PixAutomatico, BoletoPago, User, FlowState, ScannedBoleto

_PENDING: Dict[str, Dict[str, Any]] = {}
_LAST_TRANSFER: Dict[str, Dict[str, Any]] = {}

KNOWN_ALIASES = {
    "joão silva": "João Silva",
    "joao silva": "João Silva",
    "joão": "João Silva",
    "joao": "João Silva",
    "maria aparecida": "Maria Aparecida",
    "mãe": "Maria Aparecida",
    "mae": "Maria Aparecida",
    "netflix": "Netflix",
    "spotify": "Spotify",
    "smart fit": "Smart Fit",
    "academia": "Smart Fit",
    "ifood": "iFood",
    "sabesp": "SABESP",
    "enel": "ENEL",
    "vivo": "Vivo",
}

OPENING_BALANCE = 8500.0


@dataclass
class TransferDraft:
    tipo: str = "pix"
    valor: Optional[float] = None
    favorecido: Optional[str] = None
    descricao: Optional[str] = None
    boleto_id: Optional[str] = None
    chave_nova: bool = False
    needs_security: bool = False
    security_passed: bool = False
    missing: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TransferDraft":
        return cls(
            tipo=d.get("tipo") or "pix",
            valor=d.get("valor"),
            favorecido=d.get("favorecido"),
            descricao=d.get("descricao"),
            boleto_id=d.get("boleto_id"),
            chave_nova=bool(d.get("chave_nova")),
            needs_security=bool(d.get("needs_security")),
            security_passed=bool(d.get("security_passed")),
            missing=list(d.get("missing") or []),
        )


def get_pending(user_id: str) -> Optional[TransferDraft]:
    raw = _PENDING.get(user_id)
    return TransferDraft.from_dict(raw) if raw else None


def set_pending(user_id: str, draft: TransferDraft) -> None:
    _PENDING[user_id] = draft.to_dict()


def clear_pending(user_id: str) -> None:
    _PENDING.pop(user_id, None)


def get_last_transfer(user_id: str) -> Optional[Dict[str, Any]]:
    return _LAST_TRANSFER.get(user_id)


def set_last_transfer(user_id: str, data: Dict[str, Any]) -> None:
    _LAST_TRANSFER[user_id] = data


async def hydrate_flow_state(session: AsyncSession, user_id: str) -> None:
    """Restaura a jornada após reinício e permite continuidade entre canais."""
    state = await session.get(FlowState, user_id)
    if not state:
        return
    if state.pending_transfer:
        _PENDING[user_id] = dict(state.pending_transfer)
    else:
        _PENDING.pop(user_id, None)
    if state.last_transfer:
        _LAST_TRANSFER[user_id] = dict(state.last_transfer)


async def persist_flow_state(
    session: AsyncSession, user_id: str, channel: str = "flutter"
) -> None:
    state = await session.get(FlowState, user_id)
    if not state:
        state = FlowState(user_id=user_id)
        session.add(state)
    state.pending_transfer = _PENDING.get(user_id)
    state.last_transfer = _LAST_TRANSFER.get(user_id)
    state.last_channel = channel


def _fmt(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _parse_valor(text: str) -> Optional[float]:
    patterns = [
        r"R\$\s*(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?)",
        r"R\$\s*(\d+(?:[.,]\d{1,2})?)",
        r"(\d{1,3}(?:\.\d{3})+,\d{1,2})",
        r"(\d{1,3}(?:\.\d{3})+)(?:\s*reais)?",
        r"(\d+[.,]\d{1,2})\s*reais?",
        r"(?:de|valor|pix|ted|transferir|enviar|manda[r]?)\s+(\d+[.,]?\d*)",
        r"(\d+[.,]?\d*)\s*(?:reais|pra|para|pro)",
        r"\b(\d{2,6}(?:[.,]\d{1,2})?)\b",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if not m:
            continue
        raw = m.group(1)
        if re.match(r"^\d{1,3}(\.\d{3})+$", raw):
            raw = raw.replace(".", "")
        elif "," in raw and "." in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif "," in raw:
            raw = raw.replace(",", ".")
        try:
            v = float(raw)
            if 0.01 <= v <= 1_000_000:
                return round(v, 2)
        except ValueError:
            continue
    return None


def _parse_favorecido(text: str) -> Optional[str]:
    text_l = text.lower()
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    if email:
        return email.group(0)
    cpf_like = re.search(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", text)
    if cpf_like:
        return cpf_like.group(0)
    phone = re.search(r"\b(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?\d{4,5}-?\d{4}\b", text)
    if phone:
        return phone.group(0)
    for alias, canonical in sorted(KNOWN_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in text_l:
            return canonical
    m = re.search(
        r"(?:para|pra|pro|ao|à|a)\s+(?:o\s+|a\s+)?([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s]{1,40})",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        name = m.group(1).strip()
        name = re.split(
            r"\b(de|com|no|na|hoje|agora|por|via|pix|ted)\b",
            name,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" .,")
        skip = {"chave", "chave nova", "alguem", "alguém", "desconhecido", "conta"}
        if name.lower() in skip or name.lower().startswith("chave"):
            name = ""
        if len(name) >= 2 and not re.match(r"^\d", name):
            if "@" not in name and not name[0].isdigit():
                return " ".join(w.capitalize() for w in name.split())
            return name
    return None


def detect_transfer_intent(text: str) -> bool:
    t = text.lower()
    patterns = [
        r"\bpix\b", r"\bted\b", r"transferir",
        r"fazer\s+(um\s+)?pix", r"enviar\s+(um\s+)?pix", r"enviar\s+dinheiro",
        r"manda[r]?\s+(\d|r\$|um\s+pix)", r"manda[r]?\s+.+\s+(pra|para|pro)",
        r"quero\s+(fazer|enviar|mandar)\s+(um\s+)?pix",
        r"de\s+novo", r"mesm[oa]\s+(valor|pix|transfer)", r"metade",
        r"outra\s+vez", r"mesmo\s+do\s+ontem", r"igual\s+(ao|a)\s+anterior",
    ]
    return any(re.search(p, t) for p in patterns)


def apply_reference_phrases(text: str, user_id: str, draft: TransferDraft) -> TransferDraft:
    t = text.lower()
    last = get_last_transfer(user_id)
    if not last:
        return draft
    if re.search(r"\b(metade|50%)\b", t):
        if last.get("valor"):
            draft.valor = round(float(last["valor"]) / 2, 2)
        if not draft.favorecido and last.get("favorecido"):
            draft.favorecido = last["favorecido"]
        draft.tipo = last.get("tipo") or draft.tipo
    if re.search(
        r"de\s+novo|outra\s+vez|mesm[oa]\s+(valor|pix|transfer)|igual\s+(ao|a)\s+anterior|mesmo\s+do\s+ontem",
        t,
    ):
        if draft.valor is None and last.get("valor"):
            draft.valor = float(last["valor"])
        if not draft.favorecido and last.get("favorecido"):
            draft.favorecido = last["favorecido"]
        draft.tipo = last.get("tipo") or draft.tipo
    if draft.favorecido and draft.valor is None and last.get("valor"):
        if re.search(r"de\s+novo|outra\s+vez", t):
            draft.valor = float(last["valor"])
    return draft


def parse_transfer(text: str, user_id: str = "demo", base: Optional[TransferDraft] = None) -> TransferDraft:
    draft = TransferDraft.from_dict(base.to_dict()) if base else TransferDraft()
    t = text.lower()
    if re.search(r"\bted\b", t):
        draft.tipo = "ted"
    elif re.search(r"\bpix\b", t) or draft.tipo == "pix":
        draft.tipo = "pix"
    if re.search(r"chave\s*nova|desconhecido|n[aã]o\s+conhe[cç]o", t):
        draft.chave_nova = True
    valor = _parse_valor(text)
    if valor is not None:
        draft.valor = valor
    fav = _parse_favorecido(text)
    if fav:
        draft.favorecido = fav
    qm = re.search(r"[\"']([^\"']{2,80})[\"']", text)
    if qm:
        draft.descricao = qm.group(1)
    draft = apply_reference_phrases(text, user_id, draft)
    draft.missing = []
    if draft.valor is None:
        draft.missing.append("valor")
    if not draft.favorecido:
        draft.missing.append("favorecido")
    return draft


def evaluate_security(draft: TransferDraft, known_favorecidos: List[str]) -> TransferDraft:
    known_l = {k.lower() for k in known_favorecidos if k}
    fav = (draft.favorecido or "").lower()
    is_known = fav in known_l or any(fav in k or k in fav for k in known_l if len(k) > 3)
    high_value = (draft.valor or 0) >= 1000
    draft.needs_security = bool(draft.chave_nova or high_value or not is_known)
    return draft


async def list_known_favorecidos(session: AsyncSession, user_id: str) -> List[str]:
    result = await session.execute(
        select(distinct(Transaction.favorecido)).where(
            Transaction.user_id == user_id,
            Transaction.favorecido.isnot(None),
        )
    )
    return [r for r in result.scalars().all() if r]


async def list_recent_contacts(session: AsyncSession, user_id: str, limit: int = 6) -> List[Dict[str, Any]]:
    result = await session.execute(
        select(Transaction)
        .where(
            Transaction.user_id == user_id,
            Transaction.favorecido.isnot(None),
            Transaction.categoria != "renda",
        )
        .order_by(desc(Transaction.data), desc(Transaction.id))
        .limit(40)
    )
    seen = set()
    contacts = []
    for t in result.scalars().all():
        key = (t.favorecido or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        contacts.append({
            "favorecido": t.favorecido,
            "ultimo_valor": t.valor,
            "ultima_data": t.data.isoformat() if t.data else None,
            "tipo": t.tipo,
        })
        if len(contacts) >= limit:
            break
    return contacts


async def compute_saldo(session: AsyncSession, user_id: str) -> float:
    renda_q = await session.execute(
        select(func.coalesce(func.sum(Transaction.valor), 0.0)).where(
            Transaction.user_id == user_id,
            Transaction.categoria == "renda",
        )
    )
    saida_q = await session.execute(
        select(func.coalesce(func.sum(Transaction.valor), 0.0)).where(
            Transaction.user_id == user_id,
            Transaction.categoria != "renda",
        )
    )
    return round(OPENING_BALANCE + float(renda_q.scalar() or 0) - float(saida_q.scalar() or 0), 2)


async def execute_transfer(session: AsyncSession, user_id: str, draft: TransferDraft) -> Dict[str, Any]:
    if draft.valor is None or not draft.favorecido:
        return {"ok": False, "erro": "Dados incompletos"}
    saldo = await compute_saldo(session, user_id)
    if draft.valor > saldo:
        return {"ok": False, "erro": "saldo_insuficiente", "saldo": saldo, "valor": draft.valor}

    tipo = draft.tipo if draft.tipo in ("pix", "ted", "boleto", "investimento") else "pix"
    if tipo == "investimento":
        desc = draft.descricao or f"Aplicação — {draft.favorecido}"
        categoria = "investimento"
        tx_tipo = "ted"
    elif draft.boleto_id:
        desc = f"Pagamento boleto {draft.boleto_id} — {draft.favorecido}"
        categoria = "moradia"
        tipo = "boleto"
        tx_tipo = "boleto"
    else:
        desc = draft.descricao or (f"{'Pix' if tipo == 'pix' else tipo.upper()} para {draft.favorecido}")
        categoria = "transferencia"
        tx_tipo = tipo

    tx = Transaction(
        user_id=user_id,
        data=date.today(),
        tipo=tx_tipo,
        valor=float(draft.valor),
        descricao=desc,
        categoria=categoria,
        favorecido=draft.favorecido,
        is_synthetic=True,
    )
    session.add(tx)
    if draft.boleto_id:
        session.add(BoletoPago(
            user_id=user_id,
            boleto_id=draft.boleto_id,
            valor=float(draft.valor),
            beneficiario=draft.favorecido or "",
        ))
    await session.commit()
    await session.refresh(tx)
    novo_saldo = await compute_saldo(session, user_id)
    clear_pending(user_id)
    receipt = {
        "ok": True,
        "transaction_id": tx.id,
        "tipo": tipo,
        "valor": float(draft.valor),
        "favorecido": draft.favorecido,
        "descricao": desc,
        "data": date.today().isoformat(),
        "saldo_apos": novo_saldo,
        "boleto_id": draft.boleto_id,
        "comprovante_texto": (
            f"Comprovante #{tx.id}\n"
            f"{'Pix' if tipo == 'pix' else tipo.upper()} · R$ {_fmt(draft.valor)}\n"
            f"Para: {draft.favorecido}\n"
            f"Data: {date.today().isoformat()}\n"
            f"Saldo após: R$ {_fmt(novo_saldo)}"
        ),
    }
    if tipo in ("pix", "ted"):
        set_last_transfer(user_id, {"tipo": tipo, "valor": float(draft.valor), "favorecido": draft.favorecido})
    return receipt


async def open_boletos(session: AsyncSession, user_id: str) -> List[Dict[str, Any]]:
    d1 = (date.today() + timedelta(days=5)).isoformat()
    d2 = (date.today() + timedelta(days=8)).isoformat()
    d3 = (date.today() + timedelta(days=12)).isoformat()
    all_bills = [
        {"id": "SABESP_001", "valor": 187.40, "vencimento": d1, "beneficiario": "SABESP"},
        {"id": "ENEL_002", "valor": 243.10, "vencimento": d2, "beneficiario": "ENEL"},
        {"id": "VIVO_003", "valor": 119.90, "vencimento": d3, "beneficiario": "Vivo Fibra"},
    ]
    paid = await session.execute(select(BoletoPago.boleto_id).where(BoletoPago.user_id == user_id))
    paid_ids = set(paid.scalars().all())
    return [b for b in all_bills if b["id"] not in paid_ids]


async def get_scanned_boleto(
    session: AsyncSession, user_id: str, boleto_id: str
) -> Optional[Dict[str, Any]]:
    item = await session.get(ScannedBoleto, boleto_id)
    if not item or item.user_id != user_id:
        return None
    paid = await session.execute(
        select(BoletoPago.id).where(
            BoletoPago.user_id == user_id, BoletoPago.boleto_id == boleto_id
        )
    )
    if paid.scalar_one_or_none() is not None:
        return None
    return {
        "id": item.id,
        "valor": item.valor,
        "vencimento": item.vencimento.isoformat() if item.vencimento else None,
        "beneficiario": item.beneficiario,
        "linha_digitavel": item.linha_digitavel,
        "confidence": item.confidence,
        "extraction_mode": item.extraction_mode,
    }


async def configure_pix_automatico(
    session: AsyncSession, user_id: str, favorecido: str, valor: float,
    dia_mes: int = 10, descricao: Optional[str] = None,
) -> Dict[str, Any]:
    existing = await session.execute(
        select(PixAutomatico).where(
            PixAutomatico.user_id == user_id,
            PixAutomatico.favorecido == favorecido,
            PixAutomatico.ativo == True,  # noqa: E712
        )
    )
    for row in existing.scalars().all():
        row.ativo = False
    item = PixAutomatico(
        user_id=user_id,
        favorecido=favorecido,
        valor=valor,
        dia_mes=max(1, min(28, dia_mes)),
        ativo=True,
        descricao=descricao or f"Pix Automático — {favorecido}",
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {"id": item.id, "favorecido": item.favorecido, "valor": item.valor, "dia_mes": item.dia_mes, "descricao": item.descricao}


async def list_pix_automaticos(session: AsyncSession, user_id: str) -> List[Dict[str, Any]]:
    result = await session.execute(
        select(PixAutomatico).where(PixAutomatico.user_id == user_id, PixAutomatico.ativo == True)  # noqa: E712
    )
    return [
        {"id": p.id, "favorecido": p.favorecido, "valor": p.valor, "dia_mes": p.dia_mes, "descricao": p.descricao}
        for p in result.scalars().all()
    ]


async def mute_category(session: AsyncSession, user_id: str, categoria: str) -> None:
    user = await session.get(User, user_id)
    if not user:
        return
    muted = dict(user.muted_categories or {})
    muted[categoria] = True
    user.muted_categories = muted
    await session.commit()


async def is_muted(session: AsyncSession, user_id: str, categoria: str) -> bool:
    user = await session.get(User, user_id)
    if not user:
        return False
    return bool((user.muted_categories or {}).get(categoria))


def clarify_message(draft: TransferDraft) -> str:
    missing = draft.missing
    if missing == ["valor", "favorecido"]:
        return (
            "Claro. Para concluir o Pix, me diga o valor e para quem. "
            "Exemplo: 150 para João Silva. Você também pode tocar em um contato recente."
        )
    if missing == ["valor"]:
        return f"Para quem: {draft.favorecido}. Qual o valor?"
    if missing == ["favorecido"]:
        return f"Valor: R$ {_fmt(draft.valor)}. Para quem deseja enviar?"
    return "Preciso do valor e do destinatário para seguir."


def confirm_prompt(draft: TransferDraft) -> str:
    tipo_label = "Pix" if draft.tipo == "pix" else draft.tipo.upper()
    if draft.needs_security and not draft.security_passed:
        return (
            f"Atenção: valor elevado ou destinatário pouco frequente. "
            f"{tipo_label} de R$ {_fmt(draft.valor)} para {draft.favorecido}. "
            "Confirme a identidade do favorecido antes de enviar."
        )
    return (
        f"Preparei um {tipo_label} de R$ {_fmt(draft.valor)} para {draft.favorecido}. "
        "Confira os dados no card — você pode editar valor ou destinatário — e confirme para enviar."
    )

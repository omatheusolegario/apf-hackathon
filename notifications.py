"""
Regras de frequência de notificação – cap diário, janela, cooldown e opt-out.
"""
from datetime import date, datetime, time
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from models import User, NotificationLog

MAX_NOTIFICACOES_DIA = 2
JANELA_INICIO = 9
JANELA_FIM = 20

COOLDOWNS = {
    "boletos": 3,
    "pix_recorrente": 7,
    "economia": 14,
    "investimento": 30,
    "geral": 3,
}


def dentro_da_janela() -> bool:
    agora = datetime.now().time()
    return time(JANELA_INICIO, 0) <= agora <= time(JANELA_FIM, 0)


async def can_notify(session: AsyncSession, user_id: str, categoria: str) -> bool:
    user = await session.get(User, user_id)
    if not user:
        return False

    if categoria in ("pix_recorrente", "padroes_pagamento", "boletos"):
        return user.consent_padroes_pagamento
    if categoria in ("economia", "habitos_gasto"):
        return user.consent_habitos_gasto
    if categoria in ("investimento", "saldo_ocioso"):
        return user.consent_saldo_ocioso
    return True


async def em_cooldown(session: AsyncSession, user_id: str, categoria: str) -> bool:
    from sqlalchemy import select, desc

    stmt = (
        select(NotificationLog)
        .where(
            NotificationLog.user_id == user_id,
            NotificationLog.categoria == categoria,
            NotificationLog.enviado == True,  # noqa: E712
        )
        .order_by(desc(NotificationLog.created_at))
        .limit(1)
    )
    result = await session.execute(stmt)
    last = result.scalar_one_or_none()
    if not last:
        return False

    delta = (date.today() - last.created_at.date()).days
    return delta < COOLDOWNS.get(categoria, 3)


async def send_proactive_notification(
    session: AsyncSession,
    user_id: str,
    categoria: str,
    mensagem: str,
) -> Dict[str, Any]:
    if not await can_notify(session, user_id, categoria):
        log = NotificationLog(
            user_id=user_id, categoria=categoria, mensagem=mensagem,
            enviado=False, motivo="sem_consentimento",
        )
        session.add(log)
        await session.commit()
        return {"enviado": False, "motivo": "sem_consentimento"}

    user = await session.get(User, user_id)
    if not user:
        return {"enviado": False, "motivo": "usuario_nao_encontrado"}

    hoje = date.today()
    if user.ultima_notificacao_data != hoje:
        user.notificacoes_hoje = 0
        user.ultima_notificacao_data = hoje

    if user.notificacoes_hoje >= MAX_NOTIFICACOES_DIA:
        log = NotificationLog(
            user_id=user_id, categoria=categoria, mensagem=mensagem,
            enviado=False, motivo="cap_diario",
        )
        session.add(log)
        await session.commit()
        return {"enviado": False, "motivo": "cap_diario"}

    if not dentro_da_janela():
        log = NotificationLog(
            user_id=user_id, categoria=categoria, mensagem=mensagem,
            enviado=False, motivo="fora_da_janela",
        )
        session.add(log)
        await session.commit()
        return {"enviado": False, "motivo": "fora_da_janela"}

    if await em_cooldown(session, user_id, categoria):
        log = NotificationLog(
            user_id=user_id, categoria=categoria, mensagem=mensagem,
            enviado=False, motivo="cooldown",
        )
        session.add(log)
        await session.commit()
        return {"enviado": False, "motivo": "cooldown"}

    user.notificacoes_hoje += 1
    log = NotificationLog(
        user_id=user_id, categoria=categoria, mensagem=mensagem,
        enviado=True, motivo=None,
    )
    session.add(log)
    await session.commit()

    return {
        "enviado": True,
        "mensagem": mensagem,
        "categoria": categoria,
        "notificacoes_hoje": user.notificacoes_hoje,
    }

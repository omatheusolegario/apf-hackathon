"""Adaptador Telegram: conversa fora do app, confirmação financeira dentro dele."""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable
from urllib.parse import quote

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from models import ContinuationToken, ChannelIdentity, ChannelLinkCode


def validate_webhook_secret(received: str | None) -> bool:
    expected = os.getenv("TELEGRAM_WEBHOOK_SECRET") or ""
    return not expected or secrets.compare_digest(received or "", expected)


async def create_link_code(session: AsyncSession, user_id: str) -> str:
    code = secrets.token_urlsafe(9)
    session.add(ChannelLinkCode(
        code=code,
        user_id=user_id,
        provider="telegram",
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    ))
    await session.commit()
    return code


async def link_chat(
    session: AsyncSession, chat_id: int | str, code: str
) -> str | None:
    row = await session.get(ChannelLinkCode, code)
    if (
        not row
        or row.provider != "telegram"
        or row.used_at is not None
        or row.expires_at < datetime.utcnow()
    ):
        return None
    external_id = str(chat_id)
    identity = await session.get(ChannelIdentity, ("telegram", external_id))
    if not identity:
        identity = ChannelIdentity(
            provider="telegram", external_id=external_id, user_id=row.user_id
        )
        session.add(identity)
    else:
        identity.user_id = row.user_id
        identity.verified_at = datetime.utcnow()
    row.used_at = datetime.utcnow()
    await session.commit()
    return row.user_id


async def resolve_user(session: AsyncSession, chat_id: int | str) -> str | None:
    identity = await session.get(ChannelIdentity, ("telegram", str(chat_id)))
    if identity:
        return identity.user_id
    if (os.getenv("TELEGRAM_ALLOW_DEMO_USER") or "true").lower() == "true":
        return os.getenv("TELEGRAM_DEMO_USER_ID") or "demo"
    return None


async def create_continuation(
    session: AsyncSession,
    user_id: str,
    action: Dict[str, Any],
    source_channel: str = "telegram",
) -> str:
    token = secrets.token_urlsafe(24)
    session.add(ContinuationToken(
        token=token,
        user_id=user_id,
        action=action,
        source_channel=source_channel,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    ))
    await session.commit()
    return token


async def consume_continuation(
    session: AsyncSession, token: str, user_id: str
) -> Dict[str, Any] | None:
    row = await session.get(ContinuationToken, token)
    if (
        not row
        or row.user_id != user_id
        or row.used_at is not None
        or row.expires_at < datetime.utcnow()
    ):
        return None
    row.used_at = datetime.utcnow()
    await session.commit()
    return dict(row.action)


def _financial_action(cards: Iterable[Dict[str, Any]]) -> Dict[str, Any] | None:
    for card in cards:
        data = card.get("data") or {}
        kind = card.get("type")
        if kind == "transfer_confirm":
            return {"type": "resume_pending_transfer"}
        if kind == "security_check":
            return {"type": "resume_pending_transfer"}
        if kind == "bills" and data.get("boletos"):
            bill = data["boletos"][0]
            return {"type": "resume_bill", "boleto_id": bill.get("id")}
        if kind == "payment_comparison":
            return {"type": "resume_comparison", "valor": data.get("valor")}
        if kind == "investment_suggestion":
            return {"type": "resume_investment", "produto": data.get("produto")}
    return None


def format_reply(response: Dict[str, Any]) -> str:
    reply = str(response.get("text") or "")
    for card in response.get("cards") or []:
        kind, title, data = card.get("type"), card.get("title") or "", card.get("data") or {}
        if kind == "payment_comparison":
            reply += f"\n\n{title}"
            for option in data.get("opcoes") or []:
                recommended = " — recomendado" if option.get("recomendado") else ""
                reply += f"\n• {option.get('forma')}: {option.get('motivo')}{recommended}"
        elif kind == "proactive":
            reply += f"\n\n💡 {data.get('mensagem', title)}"
        elif kind == "pattern":
            reply += f"\n\n📌 {title}: R$ {data.get('valor_medio')} ({data.get('frequencia')}x)"
        elif kind == "bills":
            reply += f"\n\n{title}"
            for bill in data.get("boletos") or []:
                reply += f"\n• {bill.get('beneficiario')}: R$ {bill.get('valor')} (vence {bill.get('vencimento')})"
    return reply[:3900]


async def telegram_payload(
    session: AsyncSession, response: Dict[str, Any], user_id: str
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"text": format_reply(response)}
    action = _financial_action(response.get("cards") or [])
    if action:
        token = await create_continuation(session, user_id, action)
        public_base = (os.getenv("PUBLIC_BASE_URL") or "http://localhost:8000").rstrip("/")
        payload["reply_markup"] = {
            "inline_keyboard": [[{
                "text": "Continuar com segurança no app",
                "url": f"{public_base}/continue/{quote(token)}",
            }]]
        }
        payload["text"] += "\n\nA confirmação financeira acontece somente no app autenticado."
    return payload


async def send_message(chat_id: int | str, payload: Dict[str, Any]) -> bool:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or ""
    if not bot_token:
        return False
    body = {"chat_id": chat_id, **payload}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage", json=body
        )
    return response.status_code == 200


async def configure_webhook() -> Dict[str, Any]:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or ""
    public_base = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET") or ""
    if not bot_token or not public_base:
        raise ValueError("Defina TELEGRAM_BOT_TOKEN e PUBLIC_BASE_URL.")
    body: Dict[str, Any] = {
        "url": f"{public_base}/telegram/webhook",
        "allowed_updates": ["message", "edited_message"],
        "drop_pending_updates": False,
    }
    if secret:
        body["secret_token"] = secret
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook", json=body
        )
    response.raise_for_status()
    return response.json()

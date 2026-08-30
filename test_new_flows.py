"""Regressões das jornadas multimodal, persistente e omnichannel."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mktemp(suffix='.db')}"
os.environ["GROQ_API_KEY"] = ""
sys.path.insert(0, os.path.dirname(__file__))

from database import AsyncSessionLocal, init_db
from document_intelligence import scan_boleto
from main import _handle_card_action, process_message
from seed import seed
from telegram_integration import (
    consume_continuation,
    create_link_code,
    link_chat,
    resolve_user,
    telegram_payload,
)
from transfers import clear_pending, get_pending, hydrate_flow_state


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"  [PASS] {label}")


async def run() -> None:
    await init_db()
    await seed()

    async with AsyncSessionLocal() as session:
        scan = await scan_boleto(
            session, "demo", b"\x89PNG\r\n\x1a\nAPF-DEMO", "image/png", "sabesp.png"
        )
        check("boleto persistido", scan["id"].startswith("SCAN_"))
        check("fallback transparente", scan["extraction_mode"] == "demo_fallback")
        paid = await _handle_card_action(
            session,
            {"type": "confirm_payment", "forma": "Pix", "boleto_id": scan["id"]},
            "demo",
        )
        check("boleto fotografado pagável", bool(paid.get("cards")))

    async with AsyncSessionLocal() as session:
        code = await create_link_code(session, "demo")
        check("código de vínculo criado", bool(code))
        check("chat vinculado ao usuário", await link_chat(session, 55119999, code) == "demo")
        check("código de vínculo é uso único", await link_chat(session, 55118888, code) is None)
        check("identidade Telegram persistida", await resolve_user(session, 55119999) == "demo")

    async with AsyncSessionLocal() as session:
        await process_message(session, "Pix de 77 para João", "demo", "telegram")
        from transfers import persist_flow_state
        await persist_flow_state(session, "demo", "telegram")
        await session.commit()
        clear_pending("demo")

    async with AsyncSessionLocal() as session:
        await hydrate_flow_state(session, "demo")
        check("rascunho sobrevive reinício", get_pending("demo") is not None)
        response = await process_message(session, "Pix de 77 para João", "demo", "telegram")
        payload = await telegram_payload(session, response, "demo")
        button_url = payload["reply_markup"]["inline_keyboard"][0][0]["url"]
        token = button_url.rsplit("/", 1)[-1]
        action = await consume_continuation(session, token, "demo")
        check("handoff telegram gera token", action is not None)
        check("token é uso único", await consume_continuation(session, token, "demo") is None)

    print("Novas jornadas validadas.")


if __name__ == "__main__":
    asyncio.run(run())

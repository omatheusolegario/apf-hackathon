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
from database import _async_database_url
from document_intelligence import scan_boleto
from main import _handle_card_action, continue_in_app, process_message
from llm import sanitize_user_facing
from seed import seed, seed_user
from telegram_integration import (
    consume_continuation,
    create_link_code,
    link_chat,
    resolve_user,
    telegram_payload,
)
from transfers import clear_pending, get_pending, hydrate_flow_state, open_boletos


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"  [PASS] {label}")


async def run() -> None:
    formatted = sanitize_user_facing(
        "**Saldo**\n\n- Disponível: R$ 100\n- Reservado: R$ 20 \U0001f4b0"
    )
    check(
        "formatação Markdown é preservada",
        "**Saldo**" in formatted and "- Disponível" in formatted,
    )
    check("emojis são removidos", "\U0001f4b0" not in formatted)
    check(
        "URL Postgres seleciona driver assíncrono",
        _async_database_url("postgresql://user:pass@host/db?sslmode=require")
        == "postgresql+asyncpg://user:pass@host/db?ssl=require",
    )
    check(
        "parâmetro incompatível do Neon é removido",
        "channel_binding" not in _async_database_url(
            "postgresql://user:pass@host/db?sslmode=require&channel_binding=require"
        ),
    )
    os.environ["APP_PUBLIC_URL"] = "https://app.example"
    continuation_page = await continue_in_app("abc_123")
    check(
        "handoff possui fallback para web",
        b"https://app.example/?token=abc_123" in continuation_page.body,
    )
    await init_db()
    await seed()

    # Cada avaliador recebe uma jornada independente e pode repeti-la.
    await seed_user("demo_judgea", reset=False, initial_consents=False)
    await seed_user("demo_judgeb", reset=False, initial_consents=False)
    async with AsyncSessionLocal() as session:
        bills_a = await open_boletos(session, "demo_judgea")
        bills_b = await open_boletos(session, "demo_judgeb")
        await _handle_card_action(
            session,
            {
                "type": "confirm_payment",
                "forma": "Pix",
                "boleto_id": bills_a[0]["id"],
                "beneficiario": bills_a[0]["beneficiario"],
            },
            "demo_judgea",
        )
        check(
            "pagamento isolado por visitante",
            len(await open_boletos(session, "demo_judgea")) == 2
            and len(await open_boletos(session, "demo_judgeb")) == 3,
        )
    await seed_user("demo_judgea", reset=True)
    async with AsyncSessionLocal() as session:
        check(
            "reinício restaura jornada completa",
            len(await open_boletos(session, "demo_judgea")) == 3,
        )

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

        octet_scan = await scan_boleto(
            session,
            "demo",
            b"\x89PNG\r\n\x1a\nAPF-OCTET-STREAM",
            "application/octet-stream",
            "boleto-sem-mime.png",
        )
        check(
            "PNG válido aceito mesmo com MIME genérico do navegador",
            octet_scan["id"].startswith("SCAN_"),
        )

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

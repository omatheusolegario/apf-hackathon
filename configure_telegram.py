"""Configura o webhook do Telegram usando somente variáveis do .env."""
import asyncio

from dotenv import load_dotenv

from telegram_integration import configure_webhook


async def main() -> None:
    load_dotenv()
    result = await configure_webhook()
    print("Webhook configurado:", result.get("ok", False))


if __name__ == "__main__":
    asyncio.run(main())

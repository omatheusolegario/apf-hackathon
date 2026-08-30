import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from models import Base


def _async_database_url(raw_url: str) -> str:
    """Aceita URLs comuns de provedores e seleciona o driver assíncrono."""
    if raw_url.startswith("postgres://"):
        raw_url = "postgresql://" + raw_url[len("postgres://"):]
    if raw_url.startswith("postgresql://"):
        raw_url = "postgresql+asyncpg://" + raw_url[len("postgresql://"):]

    # O parâmetro channel_binding é específico de libpq/psycopg e não é
    # reconhecido pelo asyncpg. O TLS continua obrigatório via sslmode.
    if raw_url.startswith("postgresql+asyncpg://"):
        parts = urlsplit(raw_url)
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query)
            if key != "channel_binding"
        ]
        raw_url = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )
    return raw_url


DATABASE_URL = _async_database_url(
    os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./apf.db")
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

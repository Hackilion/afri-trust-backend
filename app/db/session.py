from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.config import settings


def _build_engine():
    url = settings.DATABASE_URL
    is_sqlite = url.startswith("sqlite")

    kwargs: dict = {
        "echo": False,
    }

    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    else:
        import ssl as _ssl

        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 5
        if settings.DATABASE_SSL:
            import certifi

            # Use certifi CA bundle (fixes verify failures on some macOS Python builds).
            ctx = _ssl.create_default_context(cafile=certifi.where())
            kwargs["connect_args"] = {"ssl": ctx}

    return create_async_engine(url, **kwargs)


engine = _build_engine()

async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

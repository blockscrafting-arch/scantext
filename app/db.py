"""
Настройка асинхронной сессии SQLAlchemy и фабрики сессий.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def get_engine(database_url: str):
    """Создаёт async engine для PostgreSQL."""
    return create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=40,
        pool_recycle=3600,
    )


def get_session_factory(engine):
    """Фабрика асинхронных сессий."""
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


# Инициализация при старте приложения (вызывается из main с URL из config)
engine = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(database_url: str) -> None:
    """Инициализирует engine и session factory. Вызвать при старте бота."""
    global engine, async_session_factory
    engine = get_engine(database_url)
    async_session_factory = get_session_factory(engine)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield async session для dependency injection в хэндлерах."""
    if async_session_factory is None:
        raise RuntimeError("DB not initialized. Call init_db() first.")
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Тип для аннотаций: сессия из get_session
SessionDep = Annotated[AsyncSession, "get_session"]

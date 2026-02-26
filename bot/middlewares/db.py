"""
Middleware: инжектит async-сессию БД в хэндлеры.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

import app.db as db_module

logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    """Добавляет в data['session'] активную сессию БД. После хэндлера делает commit/rollback."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        factory = db_module.async_session_factory
        if factory is None:
            try:
                from config import get_settings
                db_module.init_db(get_settings().DATABASE_URL)
                factory = db_module.async_session_factory
            except Exception as e:
                logger.exception("Lazy init_db failed: %s", e)
            if factory is None:
                logger.error("async_session_factory not initialized")
                return await handler(event, data)
        async with factory() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise

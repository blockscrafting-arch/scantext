"""
Middleware для защиты от спама (Throttling) на базе Redis.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    """
    Ограничивает частоту запросов от пользователя.
    Не более max_requests сообщений в течение (rate_limit + 1) секунд.
    """

    def __init__(
        self,
        redis: Redis,
        rate_limit: float = 2.0,
        max_requests: int = 5,
    ) -> None:
        self.redis = redis
        self.rate_limit = rate_limit
        self.max_requests = max_requests

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        # Не ограничивать команду /admin и кнопку админки — панель должна открываться сразу
        text = (event.text or "").strip()
        if text == "/admin" or text == "🛠 Админ-панель":
            return await handler(event, data)

        user_id = event.from_user.id if event.from_user else None
        if not user_id:
            return await handler(event, data)

        key = f"throttle:{user_id}"
        try:
            # Инкрементируем счетчик
            count = await self.redis.incr(key)
            if count == 1:
                # Устанавливаем expire только при первом запросе окна (Fixed Window)
                await self.redis.expire(key, int(self.rate_limit) + 1)
        except Exception as e:
            logger.warning("Throttling Redis error, passing update through: %s", e)
            return await handler(event, data)

        if count > self.max_requests:
            # Предупреждаем только один раз за окно, чтобы не спамить в ответ на спам
            if count == self.max_requests + 1:
                await event.answer("Слишком много запросов. Пожалуйста, подождите пару секунд.")
            return

        return await handler(event, data)

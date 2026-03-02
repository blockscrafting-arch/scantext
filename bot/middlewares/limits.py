"""
Middleware: проверка сгораемых лимитов (бесплатные + купленные) перед обработкой документа.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import User

logger = logging.getLogger(__name__)


def _is_document_event(event: TelegramObject) -> bool:
    """Проверяет, что апдейт — это отправка документа/фото (нужен лимит)."""
    if not isinstance(event, Message):
        return False
    return bool(event.photo or event.document)


class LimitsMiddleware(BaseMiddleware):
    """
    Для сообщений с фото/документом проверяет наличие лимитов.
    Сначала списываются бесплатные (free_limits_remaining), затем купленные (purchased_credits).
    Если лимитов нет — отвечает сообщением и не вызывает handler.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not _is_document_event(event):
            return await handler(event, data)
        if not isinstance(event, Message):
            return await handler(event, data)

        session: Any = data.get("session")
        if not session:
            return await handler(event, data)

        user_id = event.from_user.id if event.from_user else None
        if not user_id:
            return await handler(event, data)

        result = await session.execute(
            select(User)
            .where(User.tg_id == user_id)
            .options(selectinload(User.balance))
        )
        user = result.scalar_one_or_none()
        if not user:
            return await handler(event, data)

        total = user.free_limits_remaining
        if user.balance:
            total += user.balance.purchased_credits

        if total <= 0:
            await event.answer(
                "Лимит обработки исчерпан. Используйте /buy — выберите тариф и пополните баланс страниц."
            )
            return

        return await handler(event, data)

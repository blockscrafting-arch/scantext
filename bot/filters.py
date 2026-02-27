"""
Фильтры для хэндлеров (админ, и т.д.).
"""
from __future__ import annotations

import os
import re
from typing import cast

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db as db_module
from app.models import User
from config import get_settings


def is_superadmin(tg_id: int) -> bool:
    """Проверяет, входит ли tg_id в список суперадминистраторов (из .env)."""
    ids = list(get_settings().ADMIN_TG_IDS)
    if not ids and os.environ.get("ADMIN_TG_IDS"):
        raw = os.environ.get("ADMIN_TG_IDS", "").strip()
        ids = [int(x.strip()) for x in re.split(r"[,;\s]+", raw) if x.strip()]
    return tg_id in ids


def is_admin(tg_id: int, user: User | None = None) -> bool:
    """Проверяет, является ли пользователь администратором (суперадмин или флаг в БД)."""
    if is_superadmin(tg_id):
        return True
    if user and getattr(user, "is_admin", False):
        return True
    return False


class IsAdminFilter(BaseFilter):
    """Фильтр: только администраторы (для Message и CallbackQuery).
    Session может отсутствовать при проверке фильтра (inner middleware идёт после фильтров),
    тогда открываем разовую сессию и проверяем User.is_admin в БД.
    """

    async def __call__(self, event: Message | CallbackQuery, **kwargs: object) -> bool:
        user_tg = event.from_user
        if user_tg is None:
            return False
        if is_superadmin(user_tg.id):
            return True
        session = kwargs.get("session")
        if session is not None:
            session = cast(AsyncSession, session)
            res = await session.execute(select(User.is_admin).where(User.tg_id == user_tg.id))
            is_admin_flag = res.scalar_one_or_none()
            return bool(is_admin_flag)
        # Фильтр вызывается до инъекции session — проверяем is_admin через разовую сессию
        factory = getattr(db_module, "async_session_factory", None)
        if factory is None:
            return False
        async with factory() as one_off:
            res = await one_off.execute(select(User.is_admin).where(User.tg_id == user_tg.id))
            is_admin_flag = res.scalar_one_or_none()
            return bool(is_admin_flag)

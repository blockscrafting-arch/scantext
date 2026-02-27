"""
Фильтры для хэндлеров (админ, и т.д.).
"""
from __future__ import annotations

import os
import re
from typing import Any, cast

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db as db_module
from app.models import User
from config import get_settings

# Кэш is_admin в Redis (опционально, задаётся из main.py)
_admin_cache_redis: Any = None
ADMIN_CACHE_TTL_SEC = 120


def set_admin_cache_redis(redis: Any) -> None:
    """Устанавливает Redis-клиент для кэша is_admin (вызывается из bot/main.py)."""
    global _admin_cache_redis
    _admin_cache_redis = redis


async def invalidate_admin_cache(tg_id: int) -> None:
    """Сбрасывает кэш is_admin для пользователя (вызывать после смены прав в админке)."""
    if _admin_cache_redis is None:
        return
    try:
        await _admin_cache_redis.delete(f"admin:{tg_id}")
    except Exception:
        pass


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
        cache = _admin_cache_redis
        if cache is not None:
            try:
                cached = await cache.get(f"admin:{user_tg.id}")
                if cached is not None:
                    return cached == "1"
            except Exception:
                pass
        session = kwargs.get("session")
        if session is not None:
            session = cast(AsyncSession, session)
            res = await session.execute(select(User.is_admin).where(User.tg_id == user_tg.id))
            is_admin_flag = res.scalar_one_or_none()
            result = bool(is_admin_flag)
        else:
            factory = getattr(db_module, "async_session_factory", None)
            if factory is None:
                return False
            async with factory() as one_off:
                res = await one_off.execute(select(User.is_admin).where(User.tg_id == user_tg.id))
                is_admin_flag = res.scalar_one_or_none()
                result = bool(is_admin_flag)
        if cache is not None:
            try:
                await cache.set(
                    f"admin:{user_tg.id}",
                    "1" if result else "0",
                    ex=ADMIN_CACHE_TTL_SEC,
                )
            except Exception:
                pass
        return result

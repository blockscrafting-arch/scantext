"""
Чтение/запись динамических настроек из БД с кэшем (TTL).
Используется ботом и при необходимости Celery (sync-геттер).
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BotSettings

# In-memory кэш: key -> (value, expires_at). TTL 120 сек.
_SETTINGS_CACHE: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 120.0


def _now() -> float:
    return time.monotonic()


def _get_cached(key: str) -> str | None:
    entry = _SETTINGS_CACHE.get(key)
    if entry is None:
        return None
    val, expires = entry
    if _now() > expires:
        del _SETTINGS_CACHE[key]
        return None
    return val


def _set_cached(key: str, value: str) -> None:
    _SETTINGS_CACHE[key] = (value, _now() + _CACHE_TTL)


def _invalidate_cached(key: str) -> None:
    _SETTINGS_CACHE.pop(key, None)


async def get_setting(session: AsyncSession, key: str) -> str | None:
    """Возвращает значение настройки из БД (с кэшем)."""
    cached = _get_cached(key)
    if cached is not None:
        return cached
    result = await session.execute(select(BotSettings).where(BotSettings.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    _set_cached(key, row.value)
    return row.value


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    """Сохраняет настройку в БД и сбрасывает кэш по ключу."""
    result = await session.execute(select(BotSettings).where(BotSettings.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        session.add(BotSettings(key=key, value=value))
    else:
        row.value = value
    _invalidate_cached(key)


def get_setting_int(session: Any, key: str, default: int) -> int:
    """Синхронно читает настройку как int (для Celery). Не кэширует — сессия своя."""
    from sqlalchemy import select as _select
    result = session.execute(_select(BotSettings).where(BotSettings.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        return default
    try:
        return int(row.value)
    except (ValueError, TypeError):
        return default


def get_setting_float(session: Any, key: str, default: float) -> float:
    """Синхронно читает настройку как float (для Celery)."""
    from sqlalchemy import select as _select
    result = session.execute(_select(BotSettings).where(BotSettings.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        return default
    try:
        return float(row.value)
    except (ValueError, TypeError):
        return default


def get_setting_str_sync(session: Any, key: str, default: str = "") -> str:
    """Синхронно читает настройку как строку (для Celery)."""
    from sqlalchemy import select as _select
    result = session.execute(_select(BotSettings).where(BotSettings.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        return default
    return row.value or default


async def get_setting_int_async(session: AsyncSession, key: str, default: int) -> int:
    """Читает настройку из БД как int (с кэшем). При отсутствии или ошибке парсинга — default."""
    val = await get_setting(session, key)
    if val is None or not str(val).strip():
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


async def get_pack_size(session: AsyncSession) -> int:
    """Размер платного пакета (страниц) из БД или config."""
    from config import get_settings
    return await get_setting_int_async(session, "PAYMENT_PACK_SIZE", get_settings().PAYMENT_PACK_SIZE)


async def get_pack_price(session: AsyncSession) -> str:
    """Цена пакета (строка для ЮKassa) из БД или config."""
    from config import get_settings
    raw = await get_setting(session, "PAYMENT_PACK_PRICE")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    return get_settings().PAYMENT_PACK_PRICE


def get_pack_size_sync(session: Any) -> int:
    """Размер платного пакета для Celery (sync)."""
    from config import get_settings
    return get_setting_int(session, "PAYMENT_PACK_SIZE", get_settings().PAYMENT_PACK_SIZE)


def get_pack_price_sync(session: Any) -> str:
    """Цена пакета для Celery (sync)."""
    from config import get_settings
    return get_setting_str_sync(session, "PAYMENT_PACK_PRICE", get_settings().PAYMENT_PACK_PRICE)

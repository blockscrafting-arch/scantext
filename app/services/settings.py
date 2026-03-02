"""
Чтение/запись динамических настроек из БД с кэшем (TTL).
Используется ботом и при необходимости Celery (sync-геттер).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BotSettings, PaymentPackage

# In-memory кэш: key -> (value, expires_at). TTL 120 сек.
_SETTINGS_CACHE: dict[str, tuple[str, float]] = {}
# Кэш списка пакетов: (список DTO, время истечения)
_PACKAGES_CACHE_KEY = "payment_packages_list"
_PACKAGES_CACHE: dict[str, tuple[list[PaymentPackageData], float]] = {}
_CACHE_TTL = 120.0


@dataclass(frozen=True)
class PaymentPackageData:
    """Данные пакета для отображения и создания платежа."""

    id: int
    code: str
    name: str
    pages: int
    price: str
    currency: str
    is_active: bool
    sort_order: int


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


def _get_cached_packages() -> list[PaymentPackageData] | None:
    entry = _PACKAGES_CACHE.get(_PACKAGES_CACHE_KEY)
    if entry is None:
        return None
    val, expires = entry
    if _now() > expires:
        _PACKAGES_CACHE.pop(_PACKAGES_CACHE_KEY, None)
        return None
    return val


def _set_cached_packages(packages: list[PaymentPackageData]) -> None:
    _PACKAGES_CACHE[_PACKAGES_CACHE_KEY] = (packages, _now() + _CACHE_TTL)


def invalidate_packages_cache() -> None:
    """Сбрасывает кэш списка активных пакетов. Вызывать после любого CRUD по payment_packages."""
    _PACKAGES_CACHE.pop(_PACKAGES_CACHE_KEY, None)


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
    """Размер платного пакета (страниц) из БД или config. Legacy: для старых транзакций без snapshot."""
    from config import get_settings
    return await get_setting_int_async(session, "PAYMENT_PACK_SIZE", get_settings().PAYMENT_PACK_SIZE)


async def get_pack_price(session: AsyncSession) -> str:
    """Цена пакета (строка для ЮKassa) из БД или config. Legacy: для старых транзакций."""
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
    """Цена пакета для Celery (sync). Legacy: удалить после миграции на пакеты."""
    from config import get_settings
    return get_setting_str_sync(session, "PAYMENT_PACK_PRICE", get_settings().PAYMENT_PACK_PRICE)


def _package_to_data(pkg: PaymentPackage) -> PaymentPackageData:
    """Преобразует ORM-модель в DTO."""
    price_str = f"{pkg.price:.2f}" if pkg.price is not None else "0.00"
    return PaymentPackageData(
        id=pkg.id,
        code=pkg.code,
        name=pkg.name,
        pages=pkg.pages,
        price=price_str,
        currency=pkg.currency or "RUB",
        is_active=pkg.is_active,
        sort_order=pkg.sort_order,
    )


async def get_active_packages(session: AsyncSession) -> list[PaymentPackageData]:
    """Список активных пакетов для покупки (с кэшем)."""
    cached = _get_cached_packages()
    if cached is not None:
        return cached
    result = await session.execute(
        select(PaymentPackage)
        .where(PaymentPackage.is_active.is_(True))
        .order_by(PaymentPackage.sort_order, PaymentPackage.id)
    )
    rows = result.scalars().all()
    packages = [_package_to_data(p) for p in rows]
    _set_cached_packages(packages)
    return packages


async def get_package_by_code(session: AsyncSession, code: str) -> PaymentPackageData | None:
    """Пакет по коду (для создания платежа). Не кэшируется по коду — список уже кэшируется."""
    result = await session.execute(select(PaymentPackage).where(PaymentPackage.code == code))
    pkg = result.scalar_one_or_none()
    if pkg is None:
        return None
    return _package_to_data(pkg)


async def get_all_packages(session: AsyncSession) -> list[PaymentPackageData]:
    """Все пакеты для админки (включая неактивные). Без кэша."""
    result = await session.execute(
        select(PaymentPackage).order_by(PaymentPackage.sort_order, PaymentPackage.id)
    )
    return [_package_to_data(p) for p in result.scalars().all()]


async def get_package_by_id(session: AsyncSession, package_id: int) -> PaymentPackageData | None:
    """Пакет по id для админки."""
    result = await session.execute(select(PaymentPackage).where(PaymentPackage.id == package_id))
    pkg = result.scalar_one_or_none()
    return _package_to_data(pkg) if pkg else None

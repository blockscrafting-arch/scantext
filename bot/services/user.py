"""
Сервис пользователя: создание/получение, списание лимита.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import User, UserBalance
from app.services.settings import get_setting
from config import get_settings


async def get_or_create_user(
    session: AsyncSession,
    tg_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> User:
    """Возвращает пользователя по tg_id или создаёт нового."""
    result = await session.execute(select(User).where(User.tg_id == tg_id).options(selectinload(User.balance)))
    user = result.scalar_one_or_none()
    if user:
        user.username = username or user.username
        user.first_name = first_name or user.first_name
        user.last_name = last_name or user.last_name
        return user
    limit_str = await get_setting(session, "FREE_LIMITS_PER_MONTH")
    try:
        limit = int(limit_str) if (limit_str is not None and str(limit_str).strip()) else get_settings().FREE_LIMITS_PER_MONTH
    except (TypeError, ValueError):
        limit = get_settings().FREE_LIMITS_PER_MONTH
    user = User(
        tg_id=tg_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        free_limits_remaining=limit,
    )
    session.add(user)
    await session.flush()
    balance = UserBalance(user_id=user.id)
    session.add(balance)
    await session.flush()
    await session.refresh(user, attribute_names=["balance"])
    return user


async def spend_user_limit(session: AsyncSession, user: User) -> bool:
    """
    Списывает один лимит: сначала бесплатный, затем купленный.
    Использует блокировку строки (FOR UPDATE). Не используем lazy load — перезагружаем user с balance одним запросом.
    """
    result = await session.execute(
        select(User)
        .where(User.id == user.id)
        .options(selectinload(User.balance))
        .with_for_update()
    )
    u = result.scalar_one()
    if u.free_limits_remaining > 0:
        u.free_limits_remaining -= 1
        return True
    if u.balance and u.balance.purchased_credits > 0:
        u.balance.purchased_credits -= 1
        return True
    return False


async def refund_user_limit(session: AsyncSession, user: User) -> None:
    """Возвращает один лимит (при отмене/ошибке после списания). Начисляем в бесплатные."""
    result = await session.execute(
        select(User).where(User.id == user.id).with_for_update()
    )
    u = result.scalar_one()
    u.free_limits_remaining += 1

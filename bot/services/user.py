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


async def spend_user_limit(session: AsyncSession, user: User, amount: int = 1) -> tuple[bool, int, int]:
    """
    Списывает заданное количество лимитов: сначала бесплатные, затем купленные.
    Использует блокировку строки (FOR UPDATE).
    Возвращает: (success, deducted_free, deducted_paid)
    """
    result = await session.execute(
        select(User)
        .where(User.id == user.id)
        .options(selectinload(User.balance))
        .with_for_update()
    )
    u = result.scalar_one()
    
    total_available = u.free_limits_remaining + (u.balance.purchased_credits if u.balance else 0)
    if total_available < amount:
        return False, 0, 0
        
    deducted_free = 0
    deducted_paid = 0
    
    if u.free_limits_remaining >= amount:
        u.free_limits_remaining -= amount
        deducted_free = amount
    else:
        deducted_free = u.free_limits_remaining
        u.free_limits_remaining = 0
        deducted_paid = amount - deducted_free
        if u.balance:
            u.balance.purchased_credits -= deducted_paid
            
    return True, deducted_free, deducted_paid


async def refund_user_limit(session: AsyncSession, user: User, deducted_free: int = 1, deducted_paid: int = 0) -> None:
    """Возвращает списанные лимиты в соответствующие счетчики."""
    result = await session.execute(
        select(User).where(User.id == user.id).options(selectinload(User.balance)).with_for_update()
    )
    u = result.scalar_one()
    u.free_limits_remaining += deducted_free
    if u.balance and deducted_paid > 0:
        u.balance.purchased_credits += deducted_paid

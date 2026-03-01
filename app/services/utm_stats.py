"""
First-touch UTM-аналитика: агрегаты по первой UTM пользователя.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserUTM


def _first_touch_subquery():
    """Подзапрос: первая запись UTM по каждому user_id (по created_at, затем id)."""
    rn = func.row_number().over(
        partition_by=UserUTM.user_id,
        order_by=[UserUTM.created_at.asc(), UserUTM.id.asc()],
    ).label("rn")
    return (
        select(
            UserUTM.user_id,
            UserUTM.utm_source,
            UserUTM.utm_medium,
            UserUTM.utm_campaign,
            UserUTM.utm_term,
            UserUTM.utm_content,
            rn,
        )
        .select_from(UserUTM)
        .subquery("first_utm")
    )


async def get_first_touch_aggregates(session: AsyncSession) -> list[dict]:
    """
    Агрегация по первой UTM пользователя: группировка по source/medium/campaign,
    количество пользователей по каждой комбинации.
    """
    subq = _first_touch_subquery()
    stmt = (
        select(
            subq.c.utm_source,
            subq.c.utm_medium,
            subq.c.utm_campaign,
            func.count(subq.c.user_id).label("user_count"),
        )
        .where(subq.c.rn == 1)
        .group_by(subq.c.utm_source, subq.c.utm_medium, subq.c.utm_campaign)
        .order_by(func.count(subq.c.user_id).desc())
    )
    result = await session.execute(stmt)
    rows = result.fetchall()
    return [
        {
            "utm_source": row.utm_source or "",
            "utm_medium": row.utm_medium or "",
            "utm_campaign": row.utm_campaign or "",
            "user_count": row.user_count,
        }
        for row in rows
    ]


async def get_utm_totals(session: AsyncSession) -> dict:
    """Общие итоги: всего записей UTM и сколько пользователей имеют хотя бы одну UTM (first-touch)."""
    total_events = await session.scalar(select(func.count(UserUTM.id)))
    subq = _first_touch_subquery()
    total_users_with_utm = await session.scalar(
        select(func.count(subq.c.user_id)).select_from(subq).where(subq.c.rn == 1)
    )
    return {
        "total_utm_events": total_events or 0,
        "total_users_with_utm": total_users_with_utm or 0,
    }

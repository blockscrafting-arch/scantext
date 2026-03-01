"""
Тесты UTM-статистики (first-touch) и выгрузки.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.utm_stats import get_first_touch_aggregates, get_utm_totals


@pytest.fixture
def mock_session():
    """Мок AsyncSession с управляемыми execute/scalar."""
    session = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_get_utm_totals_returns_structure(mock_session):
    """get_utm_totals возвращает total_utm_events и total_users_with_utm."""
    mock_session.scalar = AsyncMock(side_effect=[50, 20])
    out = await get_utm_totals(mock_session)
    assert out["total_utm_events"] == 50
    assert out["total_users_with_utm"] == 20
    assert mock_session.scalar.await_count == 2


@pytest.mark.asyncio
async def test_get_utm_totals_zero(mock_session):
    """При отсутствии данных возвращаются нули."""
    mock_session.scalar = AsyncMock(side_effect=[None, None])
    out = await get_utm_totals(mock_session)
    assert out["total_utm_events"] == 0
    assert out["total_users_with_utm"] == 0


class _Row:
    def __init__(self, utm_source, utm_medium, utm_campaign, user_count):
        self.utm_source = utm_source
        self.utm_medium = utm_medium
        self.utm_campaign = utm_campaign
        self.user_count = user_count


@pytest.mark.asyncio
async def test_get_first_touch_aggregates_returns_list_of_dicts(mock_session):
    """get_first_touch_aggregates возвращает список словарей с полями source/medium/campaign/user_count."""
    mock_session.execute = AsyncMock(
        return_value=MagicMock(
            fetchall=MagicMock(
                return_value=[
                    _Row("telegram", "ads", "promo", 10),
                    _Row("email", "newsletter", "", 5),
                ]
            )
        )
    )
    out = await get_first_touch_aggregates(mock_session)
    assert len(out) == 2
    assert out[0]["utm_source"] == "telegram"
    assert out[0]["utm_medium"] == "ads"
    assert out[0]["utm_campaign"] == "promo"
    assert out[0]["user_count"] == 10
    assert out[1]["utm_source"] == "email"
    assert out[1]["utm_campaign"] == ""
    assert out[1]["user_count"] == 5


@pytest.mark.asyncio
async def test_get_first_touch_aggregates_empty(mock_session):
    """При отсутствии данных возвращается пустой список."""
    mock_session.execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))
    out = await get_first_touch_aggregates(mock_session)
    assert out == []

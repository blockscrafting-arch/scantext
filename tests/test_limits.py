"""
Тесты логики лимитов (интеграционные — требуют БД или aiosqlite).
"""
from __future__ import annotations

import pytest

# Интеграционные тесты: требуют async БД. Запуск: pytest tests/test_limits.py (с aiosqlite)
pytestmark = pytest.mark.skip(reason="Integration: need aiosqlite or PostgreSQL")


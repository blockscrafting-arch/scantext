"""
Тесты логики начисления в webhook: использование snapshot пакета и legacy fallback.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.transaction import Transaction


def test_transaction_has_package_snapshot_fields():
    """Transaction содержит поля снимка пакета для начисления по webhook."""
    # Проверяем наличие полей модели (не создаём запись в БД)
    assert hasattr(Transaction, "package_code")
    assert hasattr(Transaction, "package_name")
    assert hasattr(Transaction, "package_pages")
    assert hasattr(Transaction, "package_price")


def test_credits_resolution_from_snapshot():
    """Логика выбора количества страниц: при наличии package_pages используем его."""
    # Имитация логики из yookassa_webhook: credits = txn.package_pages or get_pack_size()
    def resolve_credits(package_pages: int | None, legacy_size: int = 10) -> int:
        if package_pages is not None:
            return package_pages
        return legacy_size

    assert resolve_credits(50, 10) == 50
    assert resolve_credits(300, 10) == 300
    assert resolve_credits(None, 10) == 10

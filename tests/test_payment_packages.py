"""
Тесты тарифных пакетов: DTO, форматирование, кэш.
"""
from __future__ import annotations

import pytest

from app.services.settings import (
    PaymentPackageData,
    invalidate_packages_cache,
)


def test_payment_package_data_has_required_fields():
    """PaymentPackageData содержит поля для оплаты и отображения."""
    pkg = PaymentPackageData(
        id=1,
        code="demo",
        name="Демо",
        pages=50,
        price="225.00",
        currency="RUB",
        is_active=True,
        sort_order=1,
    )
    assert pkg.code == "demo"
    assert pkg.name == "Демо"
    assert pkg.pages == 50
    assert pkg.price == "225.00"
    assert pkg.is_active is True


def test_format_package_button_label():
    """Формат кнопки выбора пакета."""
    from bot.keyboards.payments import format_package_button_label
    pkg = PaymentPackageData(
        id=1, code="basic", name="Базовый", pages=300,
        price="900.00", currency="RUB", is_active=True, sort_order=2,
    )
    assert "Базовый" in format_package_button_label(pkg)
    assert "300" in format_package_button_label(pkg)
    assert "900" in format_package_button_label(pkg)


def test_format_tariff_line():
    """Строка тарифа с ценой за страницу."""
    from bot.routers.payments import _format_tariff_line
    pkg = PaymentPackageData(
        id=1, code="demo", name="Демо", pages=50,
        price="225.00", currency="RUB", is_active=True, sort_order=1,
    )
    line = _format_tariff_line(pkg)
    assert "Демо" in line
    assert "50" in line
    assert "225" in line
    assert "₽" in line


def test_invalidate_packages_cache_no_error():
    """Инвалидация кэша пакетов не падает."""
    invalidate_packages_cache()
    invalidate_packages_cache()


def test_pay_package_prefix_length():
    """callback_data укладывается в лимит Telegram 64 байт."""
    from bot.keyboards.payments import PAY_PACKAGE_PREFIX
    # pay:pkg: + code (e.g. "pro") = 11 bytes
    assert len((PAY_PACKAGE_PREFIX + "pro").encode("utf-8")) <= 64

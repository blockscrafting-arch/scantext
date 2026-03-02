"""
Клавиатуры для выбора тарифного пакета и оплаты.
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.settings import PaymentPackageData

PAY_PACKAGE_PREFIX = "pay:pkg:"


def format_package_button_label(pkg: PaymentPackageData) -> str:
    """Текст кнопки: «Демо — 50 стр — 225 ₽»."""
    return f"{pkg.name} — {pkg.pages} стр — {pkg.price} ₽"


def packages_keyboard(packages: list[PaymentPackageData]) -> InlineKeyboardMarkup:
    """Клавиатура выбора пакета. callback_data = pay:pkg:{code}."""
    rows = [
        [InlineKeyboardButton(text=format_package_button_label(p), callback_data=f"{PAY_PACKAGE_PREFIX}{p.code}")]
        for p in packages
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_link_keyboard(confirmation_url: str) -> InlineKeyboardMarkup:
    """Кнопка «Оплатить» с URL подтверждения платежа ЮKassa."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оплатить", url=confirmation_url)],
        ]
    )

"""
Общие клавиатуры: главное меню (Reply).
"""
from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def get_main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Главное меню: Мой профиль, Купить лимиты, Помощь; для админа + Админ-панель."""
    buttons = [
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="💳 Купить лимиты")],
        [KeyboardButton(text="ℹ️ Помощь"), KeyboardButton(text="📜 О боте")],
        [KeyboardButton(text="📄 Документы")],
    ]
    if is_admin:
        buttons.append([KeyboardButton(text="🛠 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

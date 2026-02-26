"""
Состояния FSM админ-панели.
"""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    """Состояния админки."""

    waiting_user_query = State()       # Ввод tg_id или @username для поиска
    waiting_limit_free = State()      # Количество для бесплатных лимитов
    waiting_limit_paid = State()      # Количество для платных лимитов
    waiting_setting_value = State()   # Значение настройки (key в data)
    waiting_broadcast = State()       # Ожидание сообщения для рассылки

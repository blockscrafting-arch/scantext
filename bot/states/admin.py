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
    # Тарифные пакеты
    waiting_package_code = State()    # Код нового пакета (добавление)
    waiting_package_name = State()
    waiting_package_pages = State()
    waiting_package_price = State()
    waiting_package_sort_order = State()
    waiting_package_edit_value = State()  # Значение при редактировании (package_id, field в data)

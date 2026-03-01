"""
Inline-клавиатуры админ-панели.
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Префиксы callback_data (короткие для лимита Telegram 64 байт)
ADMIN_MAIN = "adm:main"
ADMIN_STATS = "adm:stats"
ADMIN_USERS = "adm:users"
ADMIN_BROADCAST = "adm:bc"
ADMIN_SETTINGS = "adm:set"
ADMIN_EXPORT_USERS = "adm:ex:u"
ADMIN_EXPORT_TXN = "adm:ex:t"
ADMIN_EXPORT_SUMMARY = "adm:ex:s"
ADMIN_STATS_UTM = "adm:utm"
ADMIN_EXPORT_UTM = "adm:ex:utm"
ADMIN_BACK = "adm:back"
ADMIN_CANCEL = "adm:cancel"
# Пользователь: лимиты и бан (user_id в данных)
ADMIN_USER_FREE_ADD = "adm:u:free+"
ADMIN_USER_FREE_SUB = "adm:u:free-"
ADMIN_USER_PAID_ADD = "adm:u:paid+"
ADMIN_USER_PAID_SUB = "adm:u:paid-"
ADMIN_USER_BAN = "adm:u:ban"
ADMIN_USER_UNBAN = "adm:u:unban"
ADMIN_USER_PROMOTE = "adm:u:prom"
ADMIN_USER_DEMOTE = "adm:u:dem"
ADMIN_USER_PREFIX = "adm:u:"
ADMIN_SETTING_EDIT_PREFIX = "adm:set:"
ADMIN_BROADCAST_CONFIRM = "adm:bc:yes"
ADMIN_BROADCAST_ABORT = "adm:bc:no"


def admin_broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    """Кнопки подтверждения рассылки."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Разослать", callback_data=ADMIN_BROADCAST_CONFIRM)],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=ADMIN_BROADCAST_ABORT)],
    ])


def admin_main_menu() -> InlineKeyboardMarkup:
    """Главное меню админки: Статистика, Пользователи, Рассылка, Настройки."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data=ADMIN_STATS)],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data=ADMIN_USERS)],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data=ADMIN_BROADCAST)],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data=ADMIN_SETTINGS)],
    ])


def admin_back_to_main() -> InlineKeyboardMarkup:
    """Кнопка «Назад» в главное меню админки."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=ADMIN_MAIN)],
    ])


def admin_stats_menu() -> InlineKeyboardMarkup:
    """Меню раздела Статистика: выгрузки + UTM + Назад."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 UTM-метки", callback_data=ADMIN_STATS_UTM)],
        [InlineKeyboardButton(text="📥 Пользователи (Excel)", callback_data=ADMIN_EXPORT_USERS)],
        [InlineKeyboardButton(text="📥 Транзакции (Excel)", callback_data=ADMIN_EXPORT_TXN)],
        [InlineKeyboardButton(text="📥 Сводка (Excel)", callback_data=ADMIN_EXPORT_SUMMARY)],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=ADMIN_MAIN)],
    ])


def admin_utm_menu() -> InlineKeyboardMarkup:
    """Меню раздела UTM: выгрузка Excel + Назад в Статистику."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 UTM (Excel)", callback_data=ADMIN_EXPORT_UTM)],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=ADMIN_STATS)],
    ])


def admin_cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены (выход из FSM)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=ADMIN_CANCEL)],
    ])


def admin_user_profile_keyboard(
    user_id: int, is_banned: bool, is_target_admin: bool = False, is_viewer_superadmin: bool = False
) -> InlineKeyboardMarkup:
    """Клавиатура профиля пользователя: лимиты, бан, назначение администратором."""
    ban_key = ADMIN_USER_UNBAN if is_banned else ADMIN_USER_BAN
    ban_text = "✅ Разблокировать" if is_banned else "🚫 Заблокировать"
    
    rows = [
        [
            InlineKeyboardButton(text="➕ Беспл.", callback_data=f"{ADMIN_USER_FREE_ADD}{user_id}"),
            InlineKeyboardButton(text="➖ Беспл.", callback_data=f"{ADMIN_USER_FREE_SUB}{user_id}"),
        ],
        [
            InlineKeyboardButton(text="➕ Платн.", callback_data=f"{ADMIN_USER_PAID_ADD}{user_id}"),
            InlineKeyboardButton(text="➖ Платн.", callback_data=f"{ADMIN_USER_PAID_SUB}{user_id}"),
        ],
        [InlineKeyboardButton(text=ban_text, callback_data=f"{ban_key}{user_id}")],
    ]
    
    if is_viewer_superadmin:
        admin_text = "⬇️ Убрать из админов" if is_target_admin else "⬆️ Сделать админом"
        admin_action = ADMIN_USER_DEMOTE if is_target_admin else ADMIN_USER_PROMOTE
        rows.append([InlineKeyboardButton(text=admin_text, callback_data=f"{admin_action}{user_id}")])
        
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=ADMIN_USERS)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_settings_keyboard(keys_with_values: list[tuple[str, str, str]]) -> InlineKeyboardMarkup:
    """Клавиатура настроек: (key, label, value) — кнопка с label и value, callback adm:set:KEY."""
    rows = [
        [InlineKeyboardButton(text=f"{label}: {val}", callback_data=f"{ADMIN_SETTING_EDIT_PREFIX}{key}")]
        for key, label, val in keys_with_values
    ]
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=ADMIN_MAIN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

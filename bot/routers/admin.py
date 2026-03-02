"""
Админ-панель: вход по кнопке и /admin, статистика, пользователи, рассылка, настройки, выгрузки.
Доступ только для ADMIN_TG_IDS. Управление через Inline-кнопки и FSM.
"""
from __future__ import annotations

import logging
from html import escape as html_escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models import Document, PaymentPackage, Transaction, User, UserBalance
from app.services.export import build_summary_xlsx, build_transactions_xlsx, build_users_xlsx, build_utm_xlsx
from app.services.settings import (
    get_all_packages,
    get_package_by_id,
    get_setting,
    invalidate_packages_cache,
    set_setting,
)
from app.services.utm_stats import get_first_touch_aggregates, get_utm_totals
from bot.filters import IsAdminFilter, invalidate_admin_cache, is_superadmin
from config import get_settings as get_cfg
from bot.keyboards.admin import (
    ADMIN_BACK,
    ADMIN_BROADCAST,
    ADMIN_BROADCAST_ABORT,
    ADMIN_BROADCAST_CONFIRM,
    ADMIN_CANCEL,
    ADMIN_EXPORT_SUMMARY,
    ADMIN_EXPORT_TXN,
    ADMIN_EXPORT_UTM,
    ADMIN_EXPORT_USERS,
    ADMIN_MAIN,
    ADMIN_PACKAGES,
    ADMIN_PACKAGE_ADD,
    ADMIN_PACKAGE_EDIT_PREFIX,
    ADMIN_PACKAGE_PREFIX,
    ADMIN_SETTINGS,
    ADMIN_SETTING_EDIT_PREFIX,
    ADMIN_STATS,
    ADMIN_STATS_UTM,
    ADMIN_USERS,
    ADMIN_USER_BAN,
    ADMIN_USER_PROMOTE,
    ADMIN_USER_DEMOTE,
    ADMIN_USER_FREE_ADD,
    ADMIN_USER_FREE_SUB,
    ADMIN_USER_PAID_ADD,
    ADMIN_USER_PAID_SUB,
    ADMIN_USER_UNBAN,
    admin_back_to_main,
    admin_broadcast_confirm_keyboard,
    admin_cancel_keyboard,
    admin_main_menu,
    admin_package_edit_keyboard,
    admin_packages_list_keyboard,
    admin_settings_keyboard,
    admin_stats_menu,
    admin_utm_menu,
    admin_user_profile_keyboard,
)
from bot.states.admin import AdminStates

logger = logging.getLogger(__name__)

router = Router(name="admin")


def _admin_denied_message() -> str:
    return (
        "У вас нет доступа к этому разделу. "
        "Если вы должны иметь доступ, обратитесь к администратору."
    )


# —— Точка входа: кнопка «Админ-панель» и команда /admin ——

@router.message(F.text == "🛠 Админ-панель", IsAdminFilter())
async def admin_open_panel(message: Message) -> None:
    """Открывает главное меню админки по кнопке."""
    await message.answer("Админ-панель. Выберите раздел:", reply_markup=admin_main_menu())


@router.message(Command("admin"), IsAdminFilter())
async def cmd_admin(message: Message, session) -> None:
    """Команда /admin — то же, что кнопка: главное меню админки + краткая статистика."""
    total_users = await session.scalar(select(func.count(User.id)))
    total_docs = await session.scalar(select(func.count(Document.id)))
    total_paid = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.status == "succeeded")
    ) or 0
    text = (
        "📊 Краткая сводка:\n"
        f"Пользователей: {total_users}\n"
        f"Обработано документов: {total_docs}\n"
        f"Оплачено (сумма): {total_paid} ₽\n\n"
        "Выберите раздел:"
    )
    await message.answer(text, reply_markup=admin_main_menu())


@router.message(F.text == "🛠 Админ-панель")
async def admin_denied_button(message: Message) -> None:
    """Не админ нажал кнопку «Админ-панель» — показать отказ."""
    if message.from_user:
        await message.answer(_admin_denied_message())


@router.message(Command("admin"))
async def admin_denied_command(message: Message) -> None:
    """Не админ ввёл /admin — показать отказ (хэндлер без IsAdminFilter срабатывает после провала фильтра)."""
    if message.from_user:
        await message.answer(_admin_denied_message())


@router.message(Command("my_id"))
async def cmd_my_id(message: Message) -> None:
    """Показывает Telegram ID пользователя."""
    if message.from_user:
        await message.answer(
            f"Ваш Telegram ID: <code>{message.from_user.id}</code>\n"
            "При необходимости сообщите его администратору."
        )


# —— Callback: главное меню и Назад (только админ) ——

@router.callback_query(F.data == ADMIN_MAIN, IsAdminFilter())
async def admin_cb_main(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат в главное меню админки."""
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.edit_text("Админ-панель. Выберите раздел:", reply_markup=admin_main_menu())
    await callback.answer()


@router.callback_query(F.data == ADMIN_BACK, IsAdminFilter())
async def admin_cb_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Назад — то же, что главное меню."""
    await admin_cb_main(callback, state)


@router.callback_query(F.data == ADMIN_CANCEL, IsAdminFilter())
async def admin_cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена — сброс FSM и возврат в главное меню."""
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.edit_text("Отменено. Выберите раздел:", reply_markup=admin_main_menu())
    await callback.answer()


# —— Статистика ——

@router.callback_query(F.data == ADMIN_STATS, IsAdminFilter())
async def admin_cb_stats(callback: CallbackQuery, session) -> None:
    """Раздел «Статистика»: цифры + кнопки выгрузки и Назад."""
    total_users = await session.scalar(select(func.count(User.id)))
    total_docs = await session.scalar(select(func.count(Document.id)))
    total_paid = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.status == "succeeded")
    ) or 0
    text = (
        "📊 Статистика\n\n"
        f"Пользователей: {total_users}\n"
        f"Обработано документов: {total_docs}\n"
        f"Оплачено (сумма): {total_paid} ₽\n\n"
        "Выгрузка в Excel:"
    )
    if isinstance(callback.message, Message):
        await callback.message.edit_text(text, reply_markup=admin_stats_menu())
    await callback.answer()


@router.callback_query(F.data == ADMIN_EXPORT_USERS, IsAdminFilter())
async def admin_export_users(callback: CallbackQuery, session) -> None:
    """Выгрузка списка пользователей в Excel."""
    await callback.answer("Подготовка выгрузки…")
    try:
        file_bytes = await build_users_xlsx(session)
        if isinstance(callback.message, Message):
            await callback.message.answer_document(
                BufferedInputFile(file_bytes, filename="users.xlsx"),
                caption="Выгрузка пользователей",
            )
    except Exception as e:
        logger.exception("export users failed: %s", e)
        if isinstance(callback.message, Message):
            await callback.message.answer("Не удалось сформировать выгрузку. Попробуйте позже.")


@router.callback_query(F.data == ADMIN_EXPORT_TXN, IsAdminFilter())
async def admin_export_transactions(callback: CallbackQuery, session) -> None:
    """Выгрузка транзакций в Excel."""
    await callback.answer("Подготовка выгрузки…")
    try:
        file_bytes = await build_transactions_xlsx(session)
        if isinstance(callback.message, Message):
            await callback.message.answer_document(
                BufferedInputFile(file_bytes, filename="transactions.xlsx"),
                caption="Выгрузка транзакций",
            )
    except Exception as e:
        logger.exception("export transactions failed: %s", e)
        if isinstance(callback.message, Message):
            await callback.message.answer("Не удалось сформировать выгрузку. Попробуйте позже.")


@router.callback_query(F.data == ADMIN_EXPORT_SUMMARY, IsAdminFilter())
async def admin_export_summary(callback: CallbackQuery, session) -> None:
    """Выгрузка сводки в Excel."""
    await callback.answer("Подготовка выгрузки…")
    try:
        file_bytes = await build_summary_xlsx(session)
        if isinstance(callback.message, Message):
            await callback.message.answer_document(
                BufferedInputFile(file_bytes, filename="summary.xlsx"),
                caption="Сводка",
            )
    except Exception as e:
        logger.exception("export summary failed: %s", e)
        if isinstance(callback.message, Message):
            await callback.message.answer("Не удалось сформировать выгрузку. Попробуйте позже.")


@router.callback_query(F.data == ADMIN_STATS_UTM, IsAdminFilter())
async def admin_cb_stats_utm(callback: CallbackQuery, session) -> None:
    """Раздел UTM: first-touch сводка и кнопка выгрузки."""
    totals = await get_utm_totals(session)
    aggregates = await get_first_touch_aggregates(session)
    lines = [
        "📈 UTM (first-touch)\n",
        f"Всего переходов с метками: {totals['total_utm_events']}",
        f"Пользователей с UTM: {totals['total_users_with_utm']}\n",
    ]
    if aggregates:
        lines.append("Топ по источнику/каналу/кампании:")
        for row in aggregates[:15]:
            s = row["utm_source"] or "—"
            m = row["utm_medium"] or "—"
            c = row["utm_campaign"] or "—"
            lines.append(f"  {s} | {m} | {c}: {row['user_count']} чел.")
    else:
        lines.append("Нет данных.")
    text = "\n".join(lines)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(text, reply_markup=admin_utm_menu())
    await callback.answer()


@router.callback_query(F.data == ADMIN_EXPORT_UTM, IsAdminFilter())
async def admin_export_utm(callback: CallbackQuery, session) -> None:
    """Выгрузка UTM в Excel."""
    await callback.answer("Подготовка выгрузки…")
    try:
        file_bytes = await build_utm_xlsx(session)
        if isinstance(callback.message, Message):
            await callback.message.answer_document(
                BufferedInputFile(file_bytes, filename="utm.xlsx"),
                caption="Выгрузка UTM",
            )
    except Exception as e:
        logger.exception("export utm failed: %s", e)
        if isinstance(callback.message, Message):
            await callback.message.answer("Не удалось сформировать выгрузку. Попробуйте позже.")


# —— Заглушки для остальных разделов (реализуем далее) ——

@router.callback_query(F.data == ADMIN_USERS, IsAdminFilter())
async def admin_cb_users(callback: CallbackQuery, state: FSMContext) -> None:
    """Раздел «Пользователи»: просим ввести tg_id или @username."""
    await state.set_state(AdminStates.waiting_user_query)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "👥 Поиск пользователя.\nОтправьте <b>Telegram ID</b> (число) или <b>@username</b>.\n"
            "Для отмены нажмите кнопку ниже.",
            reply_markup=admin_cancel_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data == ADMIN_BROADCAST, IsAdminFilter())
async def admin_cb_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    """Раздел «Рассылка»: просим отправить сообщение для рассылки."""
    await state.set_state(AdminStates.waiting_broadcast)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "📢 Рассылка.\nОтправьте одно сообщение (текст, фото или видео) для рассылки всем пользователям.\n"
            "Для отмены нажмите кнопку ниже.",
            reply_markup=admin_cancel_keyboard(),
        )
    await callback.answer()


@router.message(AdminStates.waiting_broadcast, (F.text | F.photo | F.video), IsAdminFilter())
async def admin_broadcast_message(message: Message, state: FSMContext) -> None:
    """Принятие сообщения для рассылки: превью и кнопки «Разослать» / «Отмена»."""
    text = None
    photo_file_id = None
    video_file_id = None
    if message.text:
        text = message.text
    elif message.photo:
        photo_file_id = message.photo[-1].file_id
        text = message.caption or ""
    elif message.video:
        video_file_id = message.video.file_id
        text = message.caption or ""
    await state.update_data(
        broadcast_text=text or "",
        broadcast_photo_file_id=photo_file_id,
        broadcast_video_file_id=video_file_id,
    )
    kbd = admin_broadcast_confirm_keyboard()
    safe_caption = html_escape(text or "(без подписи)")
    if photo_file_id:
        await message.answer_photo(photo=photo_file_id, caption=f"Превью (рассылка):\n{safe_caption}", reply_markup=kbd)
    elif video_file_id:
        await message.answer_video(video=video_file_id, caption=f"Превью (рассылка):\n{safe_caption}", reply_markup=kbd)
    else:
        await message.answer(f"Превью (рассылка):\n\n{html_escape(text or '(пусто)')}", reply_markup=kbd)
    await state.set_state(AdminStates.waiting_broadcast)  # keep state until confirm/cancel


@router.callback_query(F.data == ADMIN_BROADCAST_CONFIRM, IsAdminFilter())
async def admin_broadcast_confirm(callback: CallbackQuery, session, state: FSMContext) -> None:
    """Подтверждение рассылки: запуск Celery-задачи."""
    data = await state.get_data()
    text = data.get("broadcast_text") or ""
    photo_file_id = data.get("broadcast_photo_file_id")
    video_file_id = data.get("broadcast_video_file_id")
    await state.clear()
    try:
        from celery_app import broadcast_task
        broadcast_task.delay(text=text, photo_file_id=photo_file_id, video_file_id=video_file_id)
    except Exception as e:
        logger.exception("broadcast_task.delay failed: %s", e)
        if isinstance(callback.message, Message):
            await callback.message.edit_text("Не удалось запустить рассылку. Попробуйте позже.")
        await callback.answer("Не удалось выполнить действие.")
        return
    if isinstance(callback.message, Message):
        await callback.message.edit_text("✅ Рассылка запущена. Сообщения отправляются в фоне.")
    await callback.answer("Рассылка запущена")


@router.callback_query(F.data == ADMIN_BROADCAST_ABORT, IsAdminFilter())
async def admin_broadcast_abort(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена рассылки."""
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.edit_text("Рассылка отменена. Выберите раздел:", reply_markup=admin_main_menu())
    await callback.answer()


# Ключи настроек, редактируемых из админки: (key, human_label, type)
# Примечание: LLM/OCR сейчас читаются из .env (config); здесь — опциональные переопределения в БД на будущее.
SETTINGS_KEYS = [
    ("FREE_LIMITS_PER_MONTH", "Бесплатных страниц в месяц", "int"),
    ("PAYMENT_PACK_PRICE", "Цена пакета (₽)", "str"),
    ("PAYMENT_PACK_SIZE", "Страниц в пакете", "int"),
    ("LLM_REQUEST_TIMEOUT", "Таймаут запроса LLM (сек)", "int"),
    ("PDF_MAX_PAGES", "Макс. страниц PDF за раз", "int"),
    ("BOT_ABOUT_TEXT", "О боте (About)", "str"),
]


@router.callback_query(F.data == ADMIN_SETTINGS, IsAdminFilter())
async def admin_cb_settings(callback: CallbackQuery, session) -> None:
    """Раздел «Настройки»: список настроек с текущими значениями."""
    cfg = get_cfg()
    keys_with_values: list[tuple[str, str, str]] = []
    for key, label, _ in SETTINGS_KEYS:
        val_db = await get_setting(session, key)
        if val_db is not None:
            val = val_db
        else:
            val = str(getattr(cfg, key, ""))
        keys_with_values.append((key, label, val))
    text = "⚙️ Настройки. Нажмите параметр для изменения:"
    if isinstance(callback.message, Message):
        await callback.message.edit_text(text, reply_markup=admin_settings_keyboard(keys_with_values))
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_SETTING_EDIT_PREFIX), IsAdminFilter())
async def admin_cb_setting_edit(callback: CallbackQuery, state: FSMContext) -> None:
    """Редактирование настройки: запрос нового значения."""
    key = (callback.data or "")[len(ADMIN_SETTING_EDIT_PREFIX):].strip()
    if not key or not any(k == key for k, _, _ in SETTINGS_KEYS):
        await callback.answer("Такого параметра нет. Выберите из списка.")
        return
    await state.set_state(AdminStates.waiting_setting_value)
    await state.update_data(admin_setting_key=key)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            f"Введите новое значение для <b>{html_escape(key)}</b>. Для отмены нажмите кнопку.",
            reply_markup=admin_cancel_keyboard(),
        )
    await callback.answer()


@router.message(AdminStates.waiting_setting_value, F.text, IsAdminFilter())
async def admin_setting_value_message(message: Message, session, state: FSMContext) -> None:
    """Применение нового значения настройки."""
    data = await state.get_data()
    key = data.get("admin_setting_key")
    if not key:
        await state.clear()
        await message.answer("Время действия истекло. Выберите действие заново.", reply_markup=admin_back_to_main())
        return
    typ = next((t for k, _, t in SETTINGS_KEYS if k == key), "str")
    raw = (message.text or "").strip()
    try:
        if typ == "int":
            val = str(int(raw))
        elif typ == "float":
            val = str(float(raw))
        else:
            val = raw
    except ValueError:
        await message.answer("Неверный формат. Введите число или текст.")
        return
    await set_setting(session, key, val)
    await session.commit()
    await state.clear()

    await message.answer(f"Сохранено: {html_escape(key)} = {html_escape(val)}", reply_markup=admin_back_to_main())


# —— Тарифные пакеты ——

@router.callback_query(F.data == ADMIN_PACKAGES, IsAdminFilter())
async def admin_cb_packages(callback: CallbackQuery, session, state: FSMContext) -> None:
    """Раздел «Тарифы»: список пакетов."""
    await state.clear()
    packages = await get_all_packages(session)
    text = "📦 Тарифные пакеты. Выберите пакет для редактирования или добавьте новый:"
    if isinstance(callback.message, Message):
        await callback.message.edit_text(text, reply_markup=admin_packages_list_keyboard(packages))
    await callback.answer()


@router.callback_query(F.data == ADMIN_PACKAGE_ADD, IsAdminFilter())
async def admin_cb_package_add(callback: CallbackQuery, state: FSMContext) -> None:
    """Начать добавление пакета: запрос кода."""
    await state.set_state(AdminStates.waiting_package_code)
    await state.update_data(admin_package_create=True)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "Введите <b>код</b> нового пакета (латиница, например demo2):",
            reply_markup=admin_cancel_keyboard(),
        )
    await callback.answer()


def _parse_package_id(data: str) -> int | None:
    """Из adm:pkg:ID извлекает ID."""
    if not data or not data.startswith(ADMIN_PACKAGE_PREFIX):
        return None
    suffix = data[len(ADMIN_PACKAGE_PREFIX):].strip()
    if not suffix.isdigit():
        return None
    return int(suffix)


@router.callback_query(F.data.regexp(r"^adm:pkg:\d+$"), IsAdminFilter())
async def admin_cb_package_open(callback: CallbackQuery, session) -> None:
    """Открыть меню редактирования пакета."""
    pkg_id = _parse_package_id(callback.data or "")
    if pkg_id is None:
        await callback.answer("Ошибка.")
        return
    pkg_data = await get_package_by_id(session, pkg_id)
    if not pkg_data:
        await callback.answer("Пакет не найден.")
        return
    text = (
        f"📦 <b>{html_escape(pkg_data.name)}</b> ({pkg_data.code})\n"
        f"Страниц: {pkg_data.pages}, цена: {pkg_data.price} ₽\n"
        f"Порядок: {pkg_data.sort_order}, активен: {'да' if pkg_data.is_active else 'нет'}"
    )
    if isinstance(callback.message, Message):
        await callback.message.edit_text(text, reply_markup=admin_package_edit_keyboard(pkg_id, pkg_data.is_active))
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_PACKAGE_EDIT_PREFIX), IsAdminFilter())
async def admin_cb_package_edit_field(callback: CallbackQuery, state: FSMContext) -> None:
    """Запрос нового значения поля пакета. data = adm:pkg:e:ID:field."""
    parts = (callback.data or "").split(":")
    if len(parts) < 5:
        await callback.answer("Ошибка.")
        return
    try:
        pkg_id = int(parts[3])
    except ValueError:
        await callback.answer("Ошибка.")
        return
    field = parts[4].lower()
    if field not in ("name", "pages", "price", "order", "toggle"):
        await callback.answer("Неизвестное поле.")
        return
    if field == "toggle":
        from app.db import async_session_factory
        async with async_session_factory() as session:
            result = await session.get(PaymentPackage, pkg_id)
            if not result:
                await callback.answer("Пакет не найден.")
                return
            active_count = await session.scalar(
                select(func.count(PaymentPackage.id)).where(PaymentPackage.is_active.is_(True))
            )
            if result.is_active and (active_count or 0) <= 1:
                await callback.answer("Нельзя отключить последний активный пакет.", show_alert=True)
            else:
                result.is_active = not result.is_active
                await session.commit()
                invalidate_packages_cache()
                await callback.answer("Пакет обновлён.")
                pkg_data = await get_package_by_id(session, pkg_id)
                if pkg_data and isinstance(callback.message, Message):
                    text = (
                        f"📦 <b>{html_escape(pkg_data.name)}</b> ({pkg_data.code})\n"
                        f"Страниц: {pkg_data.pages}, цена: {pkg_data.price} ₽\n"
                        f"Порядок: {pkg_data.sort_order}, активен: {'да' if pkg_data.is_active else 'нет'}"
                    )
                    await callback.message.edit_text(text, reply_markup=admin_package_edit_keyboard(pkg_id, pkg_data.is_active))
        return
    await state.set_state(AdminStates.waiting_package_edit_value)
    await state.update_data(admin_package_id=pkg_id, admin_package_field=field)
    prompts = {
        "name": "Введите новое <b>название</b> пакета:",
        "pages": "Введите новое количество <b>страниц</b> (целое число):",
        "price": "Введите новую <b>цену</b> (руб, например 225.00):",
        "order": "Введите <b>порядок</b> (целое число):",
    }
    if isinstance(callback.message, Message):
        await callback.message.edit_text(prompts.get(field, "Введите значение:"), reply_markup=admin_cancel_keyboard())
    await callback.answer()


@router.message(AdminStates.waiting_package_edit_value, F.text, IsAdminFilter())
async def admin_package_edit_value_message(message: Message, session, state: FSMContext) -> None:
    """Применить новое значение поля пакета."""
    data = await state.get_data()
    pkg_id = data.get("admin_package_id")
    field = data.get("admin_package_field")
    if pkg_id is None or not field:
        await state.clear()
        await message.answer("Время действия истекло.", reply_markup=admin_back_to_main())
        return
    pkg = await session.get(PaymentPackage, pkg_id)
    if not pkg:
        await state.clear()
        await message.answer("Пакет не найден.", reply_markup=admin_back_to_main())
        return
    raw = (message.text or "").strip()
    if field == "name":
        pkg.name = raw or pkg.name
    elif field == "pages":
        try:
            val = int(raw)
            if val <= 0:
                await message.answer("Введите положительное число.")
                return
            pkg.pages = val
        except ValueError:
            await message.answer("Введите целое число.")
            return
    elif field == "price":
        try:
            val = float(raw.replace(",", "."))
            if val <= 0:
                await message.answer("Введите положительное число.")
                return
            from decimal import Decimal
            pkg.price = Decimal(str(round(val, 2)))
        except ValueError:
            await message.answer("Введите число (например 225.00).")
            return
    elif field == "order":
        try:
            pkg.sort_order = int(raw)
        except ValueError:
            await message.answer("Введите целое число.")
            return
    await session.commit()
    invalidate_packages_cache()
    await state.clear()
    pkg_data = await get_package_by_id(session, pkg_id)
    if pkg_data:
        text = (
            f"Сохранено. 📦 <b>{html_escape(pkg_data.name)}</b> ({pkg_data.code})\n"
            f"Страниц: {pkg_data.pages}, цена: {pkg_data.price} ₽"
        )
    else:
        text = "Сохранено."
    await message.answer(text, reply_markup=admin_back_to_main())


@router.message(AdminStates.waiting_package_code, F.text, IsAdminFilter())
async def admin_package_code_message(message: Message, session, state: FSMContext) -> None:
    raw = (message.text or "").strip().lower()
    if not raw or not raw.replace("_", "").isalnum():
        await message.answer("Код должен содержать только латинские буквы, цифры и подчёркивание.")
        return
    result = await session.execute(select(PaymentPackage).where(PaymentPackage.code == raw))
    if result.scalar_one_or_none():
        await message.answer("Пакет с таким кодом уже есть.")
        return
    await state.update_data(admin_package_code=raw)
    await state.set_state(AdminStates.waiting_package_name)
    await message.answer("Введите <b>название</b> пакета (например «Демо»):", reply_markup=admin_cancel_keyboard())


@router.message(AdminStates.waiting_package_name, F.text, IsAdminFilter())
async def admin_package_name_message(message: Message, state: FSMContext) -> None:
    await state.update_data(admin_package_name=(message.text or "").strip() or "Пакет")
    await state.set_state(AdminStates.waiting_package_pages)
    await message.answer("Введите количество <b>страниц</b> (целое число):", reply_markup=admin_cancel_keyboard())


@router.message(AdminStates.waiting_package_pages, F.text, IsAdminFilter())
async def admin_package_pages_message(message: Message, state: FSMContext) -> None:
    try:
        pages = int((message.text or "").strip())
        if pages <= 0:
            raise ValueError("must be positive")
    except ValueError:
        await message.answer("Введите целое положительное число.")
        return
    await state.update_data(admin_package_pages=pages)
    await state.set_state(AdminStates.waiting_package_price)
    await message.answer("Введите <b>цену</b> в рублях (например 225.00):", reply_markup=admin_cancel_keyboard())


@router.message(AdminStates.waiting_package_price, F.text, IsAdminFilter())
async def admin_package_price_message(message: Message, state: FSMContext) -> None:
    try:
        price = float((message.text or "").strip().replace(",", "."))
        if price <= 0:
            raise ValueError("must be positive")
    except ValueError:
        await message.answer("Введите положительное число (например 225.00).")
        return
    from decimal import Decimal
    await state.update_data(admin_package_price=str(round(price, 2)))
    await state.set_state(AdminStates.waiting_package_sort_order)
    await message.answer("Введите <b>порядок</b> отображения (целое число):", reply_markup=admin_cancel_keyboard())


@router.message(AdminStates.waiting_package_sort_order, F.text, IsAdminFilter())
async def admin_package_sort_order_message(message: Message, session, state: FSMContext) -> None:
    try:
        order = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите целое число.")
        return
    data = await state.get_data()
    code = data.get("admin_package_code", "pkg")
    name = data.get("admin_package_name", "Пакет")
    pages = data.get("admin_package_pages", 10)
    price_str = data.get("admin_package_price", "100.00")
    from decimal import Decimal
    pkg = PaymentPackage(
        code=code,
        name=name,
        pages=pages,
        price=Decimal(price_str),
        currency="RUB",
        is_active=True,
        sort_order=order,
    )
    session.add(pkg)
    await session.commit()
    invalidate_packages_cache()
    await state.clear()
    await message.answer(f"Пакет «{name}» добавлен.", reply_markup=admin_back_to_main())


# —— FSM: поиск пользователя ——

@router.message(AdminStates.waiting_user_query, F.text, IsAdminFilter())
async def admin_user_query_message(message: Message, session, state: FSMContext) -> None:
    """Обработка ввода tg_id или @username для поиска пользователя."""
    text = (message.text or "").strip()
    if not text:
        await message.answer("Введите Telegram ID (число) или @username.")
        return
    user = None
    if text.startswith("@"):
        username = text.lstrip("@")
        result = await session.execute(
            select(User).where(User.username == username).options(selectinload(User.balance))
        )
        user = result.scalar_one_or_none()
    else:
        try:
            tg_id = int(text)
            result = await session.execute(
                select(User).where(User.tg_id == tg_id).options(selectinload(User.balance))
            )
            user = result.scalar_one_or_none()
        except ValueError:
            pass
    if not user:
        await message.answer("Пользователь не найден. Проверьте ID или имя.")
        return
    await state.clear()
    docs_count = await session.scalar(select(func.count(Document.id)).where(Document.user_id == user.id))
    purchased = user.balance.purchased_credits if user.balance else 0
    created = user.created_at.strftime("%d.%m.%Y %H:%M") if user.created_at else "—"
    ban_tag = " 🚫 Заблокирован" if getattr(user, "is_banned", False) else ""
    admin_tag = " 👑 Администратор" if getattr(user, "is_admin", False) else ""
    
    safe_username = html_escape(str(user.username or "—"))
    safe_first = html_escape(str(user.first_name or ""))
    safe_last = html_escape(str(user.last_name or ""))
    profile_text = (
        f"👤 <b>Профиль</b>{ban_tag}{admin_tag}\n\n"
        f"ID: <code>{user.tg_id}</code>\n"
        f"Username: @{safe_username}\n"
        f"Имя: {safe_first} {safe_last}\n"
        f"Регистрация: {created}\n\n"
        f"Бесплатных лимитов: {user.free_limits_remaining}\n"
        f"Платных (куплено): {purchased}\n"
        f"Обработано документов: {docs_count or 0}"
    )
    
    viewer_is_super = is_superadmin(message.from_user.id) if message.from_user else False
    
    await message.answer(
        profile_text,
        reply_markup=admin_user_profile_keyboard(
            user_id=user.id,
            is_banned=getattr(user, "is_banned", False),
            is_target_admin=getattr(user, "is_admin", False),
            is_viewer_superadmin=viewer_is_super
        ),
    )


# —— Callback: изменение лимитов и бан пользователя ——

def _parse_user_id_from_callback(data: str, prefix: str) -> int | None:
    if not data.startswith(prefix) or len(data) <= len(prefix):
        return None
    try:
        return int(data[len(prefix):])
    except ValueError:
        return None


@router.callback_query(F.data.startswith(ADMIN_USER_FREE_ADD), IsAdminFilter())
async def admin_user_free_add(callback: CallbackQuery, state: FSMContext) -> None:
    """Добавить бесплатные лимиты: просим ввести количество."""
    user_id = _parse_user_id_from_callback(callback.data or "", ADMIN_USER_FREE_ADD)
    if user_id is None:
        await callback.answer("Не удалось выполнить действие.")
        return
    await state.set_state(AdminStates.waiting_limit_free)
    await state.update_data(admin_user_id=user_id, admin_limit_action="free_add")
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "Введите <b>число</b> — на сколько увеличить бесплатные лимиты. Для отмены нажмите кнопку.",
            reply_markup=admin_cancel_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_USER_FREE_SUB), IsAdminFilter())
async def admin_user_free_sub(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_limit_free)
    user_id = _parse_user_id_from_callback(callback.data or "", ADMIN_USER_FREE_SUB)
    if user_id is None:
        await callback.answer("Не удалось выполнить действие.")
        return
    await state.update_data(admin_user_id=user_id, admin_limit_action="free_sub")
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "Введите <b>число</b> — на сколько уменьшить бесплатные лимиты.",
            reply_markup=admin_cancel_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_USER_PAID_ADD), IsAdminFilter())
async def admin_user_paid_add(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = _parse_user_id_from_callback(callback.data or "", ADMIN_USER_PAID_ADD)
    if user_id is None:
        await callback.answer("Не удалось выполнить действие.")
        return
    await state.set_state(AdminStates.waiting_limit_paid)
    await state.update_data(admin_user_id=user_id, admin_limit_action="paid_add")
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "Введите <b>число</b> — на сколько увеличить платные лимиты.",
            reply_markup=admin_cancel_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_USER_PAID_SUB), IsAdminFilter())
async def admin_user_paid_sub(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = _parse_user_id_from_callback(callback.data or "", ADMIN_USER_PAID_SUB)
    if user_id is None:
        await callback.answer("Не удалось выполнить действие.")
        return
    await state.set_state(AdminStates.waiting_limit_paid)
    await state.update_data(admin_user_id=user_id, admin_limit_action="paid_sub")
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "Введите <b>число</b> — на сколько уменьшить платные лимиты.",
            reply_markup=admin_cancel_keyboard(),
        )
    await callback.answer()


@router.message(AdminStates.waiting_limit_free, F.text, IsAdminFilter())
async def admin_limit_free_apply(message: Message, session, state: FSMContext) -> None:
    """Применить изменение бесплатных лимитов."""
    data = await state.get_data()
    user_id = data.get("admin_user_id")
    action = data.get("admin_limit_action")
    if user_id is None or action not in ("free_add", "free_sub"):
        await state.clear()
        await message.answer("Время действия истекло. Выберите действие заново.", reply_markup=admin_back_to_main())
        return
    try:
        delta = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите целое число.")
        return
    if delta <= 0:
        await message.answer("Число должно быть больше 0.")
        return
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        await state.clear()
        await message.answer("Пользователь не найден. Проверьте ID или имя.")
        return
    if action == "free_add":
        user.free_limits_remaining += delta
    else:
        user.free_limits_remaining = max(0, user.free_limits_remaining - delta)
    await session.commit()
    await state.clear()
    await message.answer(
        f"Готово. Бесплатных лимитов у пользователя: {user.free_limits_remaining}.",
        reply_markup=admin_back_to_main(),
    )


@router.message(AdminStates.waiting_limit_paid, F.text, IsAdminFilter())
async def admin_limit_paid_apply(message: Message, session, state: FSMContext) -> None:
    """Применить изменение платных лимитов."""
    data = await state.get_data()
    user_id = data.get("admin_user_id")
    action = data.get("admin_limit_action")
    if user_id is None or action not in ("paid_add", "paid_sub"):
        await state.clear()
        await message.answer("Время действия истекло. Выберите действие заново.", reply_markup=admin_back_to_main())
        return
    try:
        delta = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите целое число.")
        return
    if delta <= 0:
        await message.answer("Число должно быть больше 0.")
        return
    result = await session.execute(
        select(User).where(User.id == user_id).options(selectinload(User.balance))
    )
    user = result.scalar_one_or_none()
    if not user:
        await state.clear()
        await message.answer("Пользователь не найден. Проверьте ID или имя.")
        return
    if user.balance is None:
        user.balance = UserBalance(user_id=user.id)
        session.add(user.balance)
        await session.flush()
    if action == "paid_add":
        user.balance.purchased_credits += delta
    else:
        user.balance.purchased_credits = max(0, user.balance.purchased_credits - delta)
    await session.commit()
    await state.clear()
    await message.answer(
        f"Готово. Платных лимитов у пользователя: {user.balance.purchased_credits}.",
        reply_markup=admin_back_to_main(),
    )


@router.callback_query(F.data.startswith(ADMIN_USER_BAN), IsAdminFilter())
async def admin_user_ban(callback: CallbackQuery, session) -> None:
    """Заблокировать пользователя."""
    user_id = _parse_user_id_from_callback(callback.data or "", ADMIN_USER_BAN)
    if user_id is None:
        await callback.answer("Не удалось выполнить действие.")
        return
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        await callback.answer("Пользователь не найден. Проверьте ID или имя.")
        return
    user.is_banned = True
    await session.commit()
    viewer_is_super = is_superadmin(callback.from_user.id) if callback.from_user else False
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(
            reply_markup=admin_user_profile_keyboard(
                user_id=user.id,
                is_banned=True,
                is_target_admin=getattr(user, "is_admin", False),
                is_viewer_superadmin=viewer_is_super
            ),
        )
    await callback.answer("Пользователь заблокирован")


@router.callback_query(F.data.startswith(ADMIN_USER_UNBAN), IsAdminFilter())
async def admin_user_unban(callback: CallbackQuery, session) -> None:
    """Разблокировать пользователя."""
    user_id = _parse_user_id_from_callback(callback.data or "", ADMIN_USER_UNBAN)
    if user_id is None:
        await callback.answer("Не удалось выполнить действие.")
        return
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        await callback.answer("Пользователь не найден. Проверьте ID или имя.")
        return
    user.is_banned = False
    await session.commit()
    viewer_is_super = is_superadmin(callback.from_user.id) if callback.from_user else False
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(
            reply_markup=admin_user_profile_keyboard(
                user_id=user.id,
                is_banned=False,
                is_target_admin=getattr(user, "is_admin", False),
                is_viewer_superadmin=viewer_is_super
            ),
        )
    await callback.answer("Пользователь разблокирован")


@router.callback_query(F.data.startswith(ADMIN_USER_PROMOTE), IsAdminFilter())
async def admin_user_promote(callback: CallbackQuery, session) -> None:
    """Сделать пользователя администратором (только для суперадминов)."""
    if not callback.from_user or not is_superadmin(callback.from_user.id):
        logger.info(
            "admin_user_promote: denied, viewer is not superadmin",
            extra={"viewer_tg_id": callback.from_user.id if callback.from_user else None},
        )
        await callback.answer("У вас нет прав на назначение администраторов.")
        return
        
    user_id = _parse_user_id_from_callback(callback.data or "", ADMIN_USER_PROMOTE)
    if user_id is None:
        await callback.answer("Не удалось выполнить действие.")
        return
        
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        await callback.answer("Пользователь не найден. Проверьте ID или имя.")
        return
        
    user.is_admin = True
    await session.commit()
    await invalidate_admin_cache(user.tg_id)
    await callback.answer("Назначен администратором")
    logger.info(
        "admin_user_promote: user promoted to admin",
        extra={"target_tg_id": user.tg_id, "viewer_tg_id": callback.from_user.id if callback.from_user else None},
    )
    if isinstance(callback.message, Message):
        # Перерисовываем профиль, чтобы добавить пометку 👑 Администратор
        docs_count = await session.scalar(select(func.count(Document.id)).where(Document.user_id == user.id))
        purchased = user.balance.purchased_credits if user.balance else 0
        created = user.created_at.strftime("%d.%m.%Y %H:%M") if user.created_at else "—"
        ban_tag = " 🚫 Заблокирован" if getattr(user, "is_banned", False) else ""
        admin_tag = " 👑 Администратор"
        safe_username = html_escape(str(user.username or "—"))
        safe_first = html_escape(str(user.first_name or ""))
        safe_last = html_escape(str(user.last_name or ""))
        profile_text = (
            f"👤 <b>Профиль</b>{ban_tag}{admin_tag}\n\n"
            f"ID: <code>{user.tg_id}</code>\n"
            f"Username: @{safe_username}\n"
            f"Имя: {safe_first} {safe_last}\n"
            f"Регистрация: {created}\n\n"
            f"Бесплатных лимитов: {user.free_limits_remaining}\n"
            f"Платных (куплено): {purchased}\n"
            f"Обработано документов: {docs_count or 0}"
        )
        await callback.message.edit_text(
            profile_text,
            reply_markup=admin_user_profile_keyboard(
                user_id=user.id,
                is_banned=getattr(user, "is_banned", False),
                is_target_admin=True,
                is_viewer_superadmin=True
            )
        )


@router.callback_query(F.data.startswith(ADMIN_USER_DEMOTE), IsAdminFilter())
async def admin_user_demote(callback: CallbackQuery, session) -> None:
    """Убрать пользователя из администраторов (только для суперадминов)."""
    if not callback.from_user or not is_superadmin(callback.from_user.id):
        await callback.answer("У вас нет прав на управление администраторами.")
        return
        
    user_id = _parse_user_id_from_callback(callback.data or "", ADMIN_USER_DEMOTE)
    if user_id is None:
        await callback.answer("Не удалось выполнить действие.")
        return
        
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        await callback.answer("Пользователь не найден. Проверьте ID или имя.")
        return
        
    user.is_admin = False
    await session.commit()
    await invalidate_admin_cache(user.tg_id)
    await callback.answer("Права администратора сняты")

    if isinstance(callback.message, Message):
        # Перерисовываем профиль (убираем пометку)
        docs_count = await session.scalar(select(func.count(Document.id)).where(Document.user_id == user.id))
        purchased = user.balance.purchased_credits if user.balance else 0
        created = user.created_at.strftime("%d.%m.%Y %H:%M") if user.created_at else "—"
        ban_tag = " 🚫 Заблокирован" if getattr(user, "is_banned", False) else ""
        safe_username = html_escape(str(user.username or "—"))
        safe_first = html_escape(str(user.first_name or ""))
        safe_last = html_escape(str(user.last_name or ""))
        profile_text = (
            f"👤 <b>Профиль</b>{ban_tag}\n\n"
            f"ID: <code>{user.tg_id}</code>\n"
            f"Username: @{safe_username}\n"
            f"Имя: {safe_first} {safe_last}\n"
            f"Регистрация: {created}\n\n"
            f"Бесплатных лимитов: {user.free_limits_remaining}\n"
            f"Платных (куплено): {purchased}\n"
            f"Обработано документов: {docs_count or 0}"
        )
        await callback.message.edit_text(
            profile_text,
            reply_markup=admin_user_profile_keyboard(
                user_id=user.id,
                is_banned=getattr(user, "is_banned", False),
                is_target_admin=False,
                is_viewer_superadmin=True
            )
        )

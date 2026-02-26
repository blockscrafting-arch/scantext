"""
Команда /start, принятие политики (152-ФЗ), парсинг UTM.
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qs, unquote

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.models import User, UserUTM
from bot.filters import is_admin
from bot.keyboards.common import get_main_keyboard
from bot.middlewares.policy import POLICY_CALLBACK, get_policy_text
from bot.services.user import get_or_create_user

logger = logging.getLogger(__name__)

router = Router(name="start")


def _parse_start_payload(text: str) -> str | None:
    """Извлекает payload из /start (например utm_source_telegram)."""
    if not text or not text.strip().lower().startswith("/start"):
        return None
    parts = text.strip().split(maxsplit=1)
    return parts[1] if len(parts) > 1 else None


def _parse_utm_from_payload(payload: str | None) -> dict:
    """Парсит UTM из строки вида utm_source=xxx&utm_medium=yyy или просто одну метку."""
    if not payload:
        return {}
    payload = unquote(payload)
    if "=" in payload:
        return parse_qs(payload)
    return {"raw": [payload]}


@router.message(CommandStart())
async def cmd_start(message: Message, session) -> None:
    """Обработка /start: создание пользователя, запись UTM, приветствие или экран политики."""
    user_tg = message.from_user
    if not user_tg:
        return
    user = await get_or_create_user(
        session,
        tg_id=user_tg.id,
        username=user_tg.username,
        first_name=user_tg.first_name,
        last_name=user_tg.last_name,
    )
    payload = _parse_start_payload(message.text or "")
    if payload:
        utm = _parse_utm_from_payload(payload)
        def _first(v):
            return v[0] if isinstance(v, list) and v else None
        utm_record = UserUTM(
            user_id=user.id,
            raw_start_payload=payload,
            utm_source=_first(utm.get("utm_source")),
            utm_medium=_first(utm.get("utm_medium")),
            utm_campaign=_first(utm.get("utm_campaign")),
        )
        session.add(utm_record)

    if not user.is_agreed_to_policy:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Принимаю условия", callback_data=POLICY_CALLBACK)],
            ]
        )
        await message.answer(get_policy_text(), reply_markup=keyboard)
        return

    reply_kbd = get_main_keyboard(is_admin=is_admin(user_tg.id, user))
    await message.answer(
        "Добро пожаловать! Отправьте фото или PDF-документ — я распознаю текст и верну результат.",
        reply_markup=reply_kbd,
    )


@router.callback_query(F.data == POLICY_CALLBACK)
async def on_policy_accepted(callback: CallbackQuery, session) -> None:
    """Фиксация согласия с политикой (152-ФЗ)."""
    if not callback.from_user:
        return
    from datetime import datetime, timezone
    result = await session.execute(select(User).where(User.tg_id == callback.from_user.id))
    user = result.scalar_one_or_none()
    if not user:
        await callback.answer("Сначала отправьте /start.")
        return
    user.is_agreed_to_policy = True
    user.policy_agreed_at = datetime.now(timezone.utc)
    reply_kbd = get_main_keyboard(is_admin=is_admin(callback.from_user.id, user))
    if callback.message:
        await callback.message.edit_text("Спасибо! Теперь вы можете отправлять документы и фото.")
        await callback.message.answer(
            "Выберите действие:",
            reply_markup=reply_kbd,
        )
    await callback.answer("Готово.")


@router.message(F.text == "👤 Мой профиль")
async def cmd_my_profile(message: Message, session) -> None:
    """Кнопка «Мой профиль»: баланс и лимиты."""
    if not message.from_user:
        return
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    result = await session.execute(
        select(User).where(User.tg_id == message.from_user.id).options(selectinload(User.balance))
    )
    user = result.scalar_one_or_none()
    if not user:
        await message.answer("Сначала отправьте /start.")
        return
    purchased = user.balance.purchased_credits if user.balance else 0
    text = (
        "👤 Ваш профиль\n\n"
        f"Бесплатных лимитов: {user.free_limits_remaining}\n"
        f"Платных (куплено): {purchased}\n\n"
        "Отправьте фото или PDF для распознавания текста. Покупка лимитов — кнопка «💳 Купить лимиты»."
    )
    await message.answer(text)


@router.message(Command("about"))
@router.message(F.text == "📜 О боте")
async def cmd_about(message: Message, session) -> None:
    """Команда /about для вывода информации о юр. лице."""
    from app.services.settings import get_setting
    from config import get_settings
    
    settings = get_settings()
    about_text = await get_setting(session, "BOT_ABOUT_TEXT")
    if not about_text:
        about_text = settings.BOT_ABOUT_TEXT
        
    await message.answer(about_text, disable_web_page_preview=True)


@router.message(Command("terms"))
@router.message(F.text == "📄 Документы")
async def cmd_terms(message: Message) -> None:
    """Команда /terms или кнопка «Документы» — просмотр юридических документов."""
    await message.answer(get_policy_text(), disable_web_page_preview=True)


@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message) -> None:
    """Кнопка «Помощь»."""
    await message.answer(
        "Отправьте фото или многостраничный PDF — бот распознает текст (OCR) и пришлёт результат.\n\n"
        "Лимиты: бесплатно даётся ограниченное число страниц в месяц, остальное — по подписке.\n"
        "Команда /buy или кнопка «💳 Купить лимиты» — пополнение платных страниц.\n\n"
        "Юридическая информация: /about\n"
        "Документы (Оферта, Политика): /terms"
    )


@router.message(F.text)
async def on_any_text(message: Message) -> None:
    """Ответ на произвольный текст: подсказка, что отправлять фото или PDF."""
    await message.answer(
        "Отправьте фото или PDF-документ — я распознаю текст и верну результат.\n"
        "Команды: /start, /buy, /help."
    )

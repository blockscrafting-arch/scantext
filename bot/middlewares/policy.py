"""
Middleware 152-ФЗ: блокирует действия пользователя до принятия политики конфиденциальности.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy import select

from app.models import User
from bot.filters import is_admin
from config import get_settings

logger = logging.getLogger(__name__)

POLICY_CALLBACK = "policy_accepted"

# Fallback-ссылки, если в конфиге не заданы (ваши документы на Telegraph)
_DEFAULT_PRIVACY_URL = "https://telegra.ph/Politika-konfidencialnosti-02-23-23"
_DEFAULT_OFFER_URL = "https://telegra.ph/Polzovatelskoe-soglashenie-02-23-17"
_DEFAULT_CONSENT_URL = "https://telegra.ph/SOGLASIE-NA-OBRABOTKU-PERSONALNYH-DANNYH-02-23-7"


def get_policy_text() -> str:
    """Возвращает текст политики с ссылками из конфига или fallback на telegra.ph."""
    from html import escape as html_escape
    settings = get_settings()
    privacy_url = (settings.PRIVACY_POLICY_URL or "").strip() or _DEFAULT_PRIVACY_URL
    terms_url = (settings.TERMS_URL or "").strip() or _DEFAULT_OFFER_URL
    consent_url = (settings.CONSENT_PD_URL or "").strip() or _DEFAULT_CONSENT_URL
    safe_privacy = html_escape(privacy_url, quote=True)
    safe_terms = html_escape(terms_url, quote=True)
    safe_consent = html_escape(consent_url, quote=True)
    return (
        "Для использования бота необходимо принять Политику конфиденциальности и Оферту (Условия использования).\n\n"
        "Отправляя персональные данные (фото, документы) и совершая платежи, вы даете Согласие на обработку данных "
        "в соответствии с 152-ФЗ и нашей политикой.\n\n"
        f"📄 <a href='{safe_privacy}'>Политика конфиденциальности</a>\n"
        f"📄 <a href='{safe_terms}'>Пользовательское соглашение</a>\n"
        f"📄 <a href='{safe_consent}'>Согласие на обработку ПД (152-ФЗ)</a>"
    )


class PolicyMiddleware(BaseMiddleware):
    """
    Если пользователь не принял политику (is_agreed_to_policy=False),
    перехватывает все апдейты кроме /start и callback policy_accepted,
    и показывает сообщение с кнопкой принятия.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        session: Any = data.get("session")
        if not session:
            return await handler(event, data)
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        user = await self._get_user(event, session)
        if user is None:
            # Новый пользователь: разрешаем только /start
            if await self._is_allowed_event(event):
                return await handler(event, data)
            if isinstance(event, Message) and event.text:
                await event.answer("Сначала отправьте /start для регистрации.")
            elif isinstance(event, CallbackQuery):
                if isinstance(event.message, Message):
                    await event.message.edit_text("Сначала отправьте /start.")
                await event.answer()
            return

        tg_id = event.from_user.id if event.from_user else 0
        if getattr(user, "is_banned", False) and not is_admin(tg_id, user):
            if isinstance(event, Message):
                await event.answer("Вы заблокированы. Обратитесь к администратору.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Вы заблокированы.", show_alert=True)
            return

        if user.is_agreed_to_policy:
            return await handler(event, data)

        # Разрешаем только /start и callback "policy_accepted"
        if await self._is_allowed_event(event):
            return await handler(event, data)

        # Показываем экран принятия политики
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Принимаю условия", callback_data=POLICY_CALLBACK)],
            ]
        )
        if isinstance(event, Message) and event.text:
            await event.answer(get_policy_text(), reply_markup=keyboard)
        elif isinstance(event, CallbackQuery):
            if isinstance(event.message, Message):
                await event.message.edit_text(get_policy_text(), reply_markup=keyboard)
            await event.answer()
        return

    async def _get_user(self, event: TelegramObject, session) -> User | None:
        """Извлекает user_id из апдейта и загружает User из БД."""
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id
        if user_id is None:
            return None
        result = await session.execute(select(User).where(User.tg_id == user_id))
        return result.scalar_one_or_none()

    async def _is_allowed_event(self, event: TelegramObject) -> bool:
        """Разрешены: команда /start, /terms и callback policy_accepted."""
        if isinstance(event, Message) and event.text:
            text = event.text.strip().lower()
            if text.startswith("/start") or text.startswith("/terms") or text.startswith("/about") or text in ("📜 о боте", "📄 документы"):
                return True
        if isinstance(event, CallbackQuery) and event.data == POLICY_CALLBACK:
            return True
        return False

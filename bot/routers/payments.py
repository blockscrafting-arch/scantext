"""
Покупка лимитов: /buy, создание платежа ЮKassa, отправка ссылки.
Лимит на число активных (pending) платежей на пользователя — защита от спама и перегрузки.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from app.models import Transaction, User
from app.services.settings import get_pack_price, get_pack_size
from app.yookassa_service import create_payment

router = Router(name="payments")
logger = logging.getLogger(__name__)

MAX_PENDING_PAYMENTS = 5
PENDING_PAYMENTS_WINDOW_MINUTES = 30


async def _do_buy(message: Message, session) -> bool:
    """Общая логика покупки: создаёт платёж и отправляет ссылку. Возвращает True при успехе."""
    if not message.from_user:
        return False
    result = await session.execute(select(User).where(User.tg_id == message.from_user.id))
    user = result.scalar_one_or_none()
    if not user:
        await message.answer("Сначала отправьте /start.")
        return False

    # Лимит активных (pending) платежей на пользователя за последние N минут
    since = datetime.now(timezone.utc) - timedelta(minutes=PENDING_PAYMENTS_WINDOW_MINUTES)
    pending_count_result = await session.execute(
        select(func.count(Transaction.id)).where(
            Transaction.user_id == user.id,
            Transaction.status == "pending",
            Transaction.created_at >= since,
        )
    )
    pending_count = pending_count_result.scalar() or 0
    if pending_count >= MAX_PENDING_PAYMENTS:
        await message.answer(
            "Слишком много активных оплат. Дождитесь завершения или отмены одной из них, затем попробуйте снова."
        )
        return False

    pack_price = await get_pack_price(session)
    pack_size = await get_pack_size(session)
    
    idem_key = str(uuid.uuid4())
    
    # Сначала создаём транзакцию со статусом pending
    txn = Transaction(
        user_id=user.id,
        idempotency_key=idem_key,
        amount=pack_price,
        currency="RUB",
        status="pending",
        description=f"Пакет {pack_size} страниц OCR",
    )
    session.add(txn)
    await session.commit()
    
    try:
        payment = await create_payment(
            amount=pack_price,
            description=f"Пакет {pack_size} страниц OCR",
            metadata={"user_tg_id": str(message.from_user.id), "user_id": str(user.id)},
            idempotence_key=idem_key,
        )
    except Exception as e:
        logger.exception("YooKassa create_payment failed: %s", e)
        session.delete(txn)
        await session.commit()
        await message.answer("Ошибка создания платежа. Попробуйте позже.")
        return False
        
    # Сохраняем payment_id
    txn.yookassa_payment_id = payment.id
    await session.commit()
    
    if not payment.confirmation_url:
        await message.answer("Не удалось получить ссылку на оплату.")
        return False
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оплатить", url=payment.confirmation_url)],
        ]
    )
    await message.answer(
        f"Оплата {pack_price} ₽ — пакет из {pack_size} страниц.\n"
        "После оплаты баланс пополнится автоматически.",
        reply_markup=keyboard,
    )
    return True


@router.message(Command("buy"))
async def cmd_buy(message: Message, session) -> None:
    """Команда /buy — создаёт платёж и отправляет ссылку на оплату."""
    await _do_buy(message, session)


@router.message(F.text == "💳 Купить лимиты")
async def btn_buy(message: Message, session) -> None:
    """Кнопка «Купить лимиты» — то же, что /buy."""
    await _do_buy(message, session)

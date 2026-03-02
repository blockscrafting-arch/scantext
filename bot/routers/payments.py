"""
Покупка лимитов: /buy — выбор пакета, создание платежа ЮKassa, отправка ссылки.
Лимит на число активных (pending) платежей на пользователя — защита от спама.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import delete, func, select

from app.models import Transaction, User
from app.services.settings import PaymentPackageData, get_active_packages, get_package_by_code, get_setting
from app.yookassa_service import create_payment
from bot.keyboards.payments import PAY_PACKAGE_PREFIX, packages_keyboard, payment_link_keyboard
from config import get_settings

router = Router(name="payments")
logger = logging.getLogger(__name__)

MAX_PENDING_PAYMENTS = 5
PENDING_PAYMENTS_WINDOW_MINUTES = 30


def _format_tariff_line(pkg: PaymentPackageData) -> str:
    """Строка тарифа с ценой за страницу: «Демо — 50 стр — 225 ₽ (4,5 ₽/стр)»."""
    try:
        price_float = float(pkg.price)
        per_page = price_float / pkg.pages if pkg.pages else 0
        per_page_str = f"{per_page:.1f}".replace(".", ",")
    except (ValueError, TypeError):
        per_page_str = "—"
    return f"{pkg.name} — {pkg.pages} стр — {pkg.price} ₽ ({per_page_str} ₽/стр)"


async def _show_packages(message: Message, session) -> bool:
    """Показать список пакетов для выбора. Возвращает True если пакеты есть."""
    packages = await get_active_packages(session)
    if not packages:
        await message.answer("Покупка временно недоступна. Попробуйте позже.")
        return False
    header_raw = await get_setting(session, "PAYMENT_TARIFFS_HEADER")
    if header_raw and str(header_raw).strip():
        header = str(header_raw).strip()
    else:
        header = get_settings().PAYMENT_TARIFFS_HEADER or "Выберите тариф:"
    lines = [_format_tariff_line(p) for p in packages]
    text = header + "\n\n" + "\n".join(lines)
    await message.answer(text, reply_markup=packages_keyboard(packages))
    return True


async def _do_buy_with_package(callback: CallbackQuery, session, package_code: str) -> bool:
    """Создать платёж по выбранному пакету. Возвращает True при успехе."""
    if not callback.message or not callback.from_user:
        return False
    message = callback.message

    result = await session.execute(select(User).where(User.tg_id == callback.from_user.id))
    user = result.scalar_one_or_none()
    if not user:
        await callback.answer("Сначала отправьте /start.")
        return False

    pkg = await get_package_by_code(session, package_code)
    if not pkg or not pkg.is_active:
        await callback.answer("Этот тариф недоступен.")
        return False

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
        await callback.answer(
            "Слишком много активных оплат. Дождитесь завершения или отмены одной из них.",
            show_alert=True,
        )
        return False

    amount_decimal = Decimal(pkg.price)
    idem_key = str(uuid.uuid4())

    txn = Transaction(
        user_id=user.id,
        idempotency_key=idem_key,
        amount=amount_decimal,
        currency="RUB",
        status="pending",
        description=f"{pkg.name}: {pkg.pages} страниц",
        package_code=pkg.code,
        package_name=pkg.name,
        package_pages=pkg.pages,
        package_price=amount_decimal,
    )
    session.add(txn)
    await session.commit()

    try:
        payment = await create_payment(
            amount=pkg.price,
            description=f"Пакет {pkg.name}: {pkg.pages} стр.",
            metadata={
                "user_tg_id": str(callback.from_user.id),
                "user_id": str(user.id),
                "package_code": pkg.code,
                "txn_id": str(txn.id),
            },
            idempotence_key=idem_key,
        )
    except Exception as e:
        logger.exception("YooKassa create_payment failed: %s", e)
        await session.execute(delete(Transaction).where(Transaction.id == txn.id))
        await session.commit()
        demo_url = get_settings().DEMO_PAYMENT_URL
        if demo_url:
            await message.edit_text(
                f"Оплата {pkg.price} ₽ — пакет «{pkg.name}», {pkg.pages} страниц.\n"
                "После оплаты баланс пополнится автоматически.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="Оплатить", url=demo_url)]]
                ),
            )
        else:
            await message.edit_text("Не удалось создать платёж. Попробуйте позже.")
        await callback.answer()
        return False

    txn.yookassa_payment_id = payment.id
    await session.commit()

    if not payment.confirmation_url:
        await message.edit_text("Не удалось получить ссылку на оплату.")
        await callback.answer()
        return False

    await message.edit_text(
        f"Оплата {pkg.price} ₽ — пакет «{pkg.name}», {pkg.pages} страниц.\n"
        "После оплаты баланс пополнится автоматически.",
        reply_markup=payment_link_keyboard(payment.confirmation_url),
    )
    await callback.answer()
    return True


@router.message(Command("buy"))
async def cmd_buy(message: Message, session) -> None:
    """Команда /buy — показать тарифы и кнопки выбора пакета."""
    await _show_packages(message, session)


@router.message(F.text == "💳 Купить лимиты")
async def btn_buy(message: Message, session) -> None:
    """Кнопка «Купить лимиты» — показать тарифы."""
    await _show_packages(message, session)


@router.callback_query(F.data.startswith(PAY_PACKAGE_PREFIX))
async def cb_package_selected(callback: CallbackQuery, session) -> None:
    """Пользователь выбрал пакет — создаём платёж и отправляем ссылку."""
    code = (callback.data or "").removeprefix(PAY_PACKAGE_PREFIX).strip()
    if not code:
        await callback.answer("Неверный выбор.")
        return
    await _do_buy_with_package(callback, session, code)

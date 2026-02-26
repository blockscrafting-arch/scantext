"""
Обработчик webhook ЮKassa: обновление статуса платежа и начисление баланса.
Верификация через API перед начислением; Pydantic-валидация тела; защита от гонки (FOR UPDATE).
"""
from __future__ import annotations

import logging
from decimal import Decimal
import ipaddress

from aiohttp import web
from aiogram import Bot
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import async_session_factory
from app.models import Transaction, User, UserBalance
from app.services.settings import get_pack_size
from app.yookassa_service import YooKassaWebhookPayload, get_payment_status
from config import get_settings

logger = logging.getLogger(__name__)


YOOKASSA_IPS = [
    ipaddress.ip_network("185.71.76.0/27"),
    ipaddress.ip_network("185.71.77.0/27"),
    ipaddress.ip_network("77.75.153.0/25"),
    ipaddress.ip_network("77.75.156.11/32"),
    ipaddress.ip_network("77.75.156.35/32"),
    ipaddress.ip_network("77.75.154.128/25"),
    ipaddress.ip_network("2a02:5180::/32"),
]


def _is_valid_yookassa_ip(ip_str: str | None) -> bool:
    """Проверяет, входит ли IP в список разрешённых подсетей ЮKassa."""
    if not ip_str or not isinstance(ip_str, str):
        return False
    try:
        ip = ipaddress.ip_address(ip_str.strip())
        for net in YOOKASSA_IPS:
            if ip in net:
                return True
    except ValueError:
        pass
    return False


def _amount_matches(api_value: str | None, txn_amount: Decimal) -> bool:
    """Сравнивает сумму из API (строка) с суммой транзакции (Decimal). Без float, с нормализацией до 2 знаков."""
    if api_value is None:
        return False
    if isinstance(api_value, str):
        api_value = api_value.strip()
    if not api_value:
        return False
    try:
        api_decimal = Decimal(api_value).quantize(Decimal("0.01"))
        return api_decimal == txn_amount.quantize(Decimal("0.01"))
    except Exception:
        return False


async def yookassa_webhook_handler(request: web.Request) -> web.Response:
    """
    POST /yookassa/webhook — тело JSON от ЮKassa.
    При payment.succeeded верифицируем платёж через API, затем обновляем Transaction и начисляем purchased_credits.
    """
    if request.method != "POST":
        return web.Response(status=405)

    # Nginx передает реальный IP клиента в заголовке X-Real-IP
    client_ip = request.headers.get("X-Real-IP") or getattr(request, "remote", None)
    if not _is_valid_yookassa_ip(client_ip):
        settings = get_settings()
        if "ngrok" not in (settings.WEBHOOK_HOST or ""):
            logger.warning("Webhook from invalid IP: %s", client_ip)
            return web.Response(status=403)

    try:
        body = await request.json()
    except Exception as e:
        logger.warning("Invalid webhook body: %s", e)
        return web.Response(status=400)

    try:
        payload = YooKassaWebhookPayload.model_validate(body)
    except ValidationError as e:
        logger.warning("Webhook payload validation failed: %s", e)
        return web.Response(status=400)

    event = payload.event
    obj = payload.object
    metadata = obj.metadata or {}
    if event not in ("payment.succeeded", "payment.canceled"):
        return web.Response(status=200, text="ok")

    payment_id = obj.id
    status = obj.status
    if not payment_id:
        return web.Response(status=200, text="ok")

    if async_session_factory is None:
        logger.error("async_session_factory not initialized")
        return web.Response(status=500)

    bot: Bot | None = request.app.get("bot")

    async with async_session_factory() as session:
        # Блокировка строки для защиты от гонки при двойной доставке webhook
        result = await session.execute(
            select(Transaction)
            .where(Transaction.yookassa_payment_id == payment_id)
            .with_for_update()
        )
        txn = result.scalar_one_or_none()
        if not txn:
            logger.warning("Transaction not found for payment %s", payment_id)
            return web.Response(status=200, text="ok")

        if txn.status in ("succeeded", "canceled"):
            return web.Response(status=200, text="ok")

        txn.status = status
        user_id = txn.user_id

        # Согласованность metadata с транзакцией перед использованием user_tg_id
        user_tg_id_raw = metadata.get("user_tg_id")
        metadata_user_id = metadata.get("user_id")
        user_tg_id = None
        if metadata_user_id == str(txn.user_id) and user_tg_id_raw:
            try:
                user_tg_id = int(user_tg_id_raw)
            except (TypeError, ValueError):
                pass

        if event == "payment.canceled":
            logger.info("Payment %s canceled for user_id=%s", payment_id, user_id)
            await session.commit()
            if bot and user_tg_id:
                try:
                    await bot.send_message(
                        chat_id=user_tg_id,
                        text="К сожалению, платеж был отменен или не прошел. "
                             "Попробуйте еще раз с помощью команды /buy."
                    )
                except Exception as e:
                    logger.warning("Failed to send cancellation message: %s", e)
            return web.Response(status=200, text="ok")

        # event == "payment.succeeded" — верификация через API перед начислением
        try:
            payment_data = await get_payment_status(payment_id)
        except Exception as e:
            logger.warning("get_payment_status failed for %s: %s", payment_id, e)
            return web.Response(status=500)

        api_status = payment_data.get("status")
        if api_status != "succeeded":
            logger.warning("Payment %s API status is %s, not succeeded", payment_id, api_status)
            return web.Response(status=200, text="ok")

        api_amount = payment_data.get("amount", {})
        api_value = api_amount.get("value") if isinstance(api_amount, dict) else None
        if not _amount_matches(api_value, txn.amount):
            logger.warning(
                "Payment %s amount mismatch: api=%s txn=%s",
                payment_id, api_value, txn.amount
            )
            return web.Response(status=200, text="ok")

        result_user = await session.execute(
            select(User).where(User.id == user_id).options(selectinload(User.balance))
        )
        user = result_user.scalar_one_or_none()
        if not user:
            logger.warning("User %s not found for payment %s", user_id, payment_id)
            return web.Response(status=200, text="ok")
        if user.balance is None:
            balance = UserBalance(user_id=user.id)
            session.add(balance)
            await session.flush()
            await session.refresh(user, attribute_names=["balance"])

        pack_size = await get_pack_size(session)
        user.balance.purchased_credits += pack_size
        await session.commit()
        logger.info("Payment %s succeeded, user_id=%s credits+=%s", payment_id, user_id, pack_size)

        if bot and user_tg_id:
            try:
                await bot.send_message(
                    chat_id=user_tg_id,
                    text=f"✅ Оплата прошла успешно!\n"
                         f"Вам начислено {pack_size} страниц.\n"
                         f"Ваш текущий баланс купленных: {user.balance.purchased_credits} стр."
                )
            except Exception as e:
                logger.warning("Failed to send success message: %s", e)

    return web.Response(status=200, text="ok")

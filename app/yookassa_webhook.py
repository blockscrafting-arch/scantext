"""
Обработчик webhook ЮKassa: обновление статуса платежа и начисление баланса.

Контракт модерации (верификация входящих уведомлений):
1. IP allowlist — запрос принимается только с официальных подсетей ЮKassa (YOOKASSA_IPS).
2. GET /payments/{id} — перед начислением баланса статус и сумма проверяются через API ЮKassa.
3. Сверка суммы — amount из API должен совпадать с суммой нашей транзакции (до копеек).
4. Идемпотентность — блокировка по yookassa_payment_id (FOR UPDATE), повторная обработка
   уже succeeded/canceled не выполняет начисление.

Примечание: YOOKASSA_WEBHOOK_SECRET в конфиге не используется — в текущем API ЮKassa
для HTTP-уведомлений подпись/HMAC не передаётся; аутентификация по документации только
через IP и проверку объекта через API (см. yookassa.ru/developers/using-api/webhooks).
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
from app.models import RefundProcessed, Transaction, User, UserBalance
from app.services.settings import get_pack_size
from app.yookassa_service import (
    YooKassaWebhookPayload,
    YooKassaRefundWebhookPayload,
    get_payment_status,
)
from config import get_settings

logger = logging.getLogger(__name__)

# Outcome-коды для фильтрации логов модерации (без PII в коде)
WEBHOOK_OUTCOME_ACCEPTED = "accepted"
WEBHOOK_OUTCOME_IGNORED_DUPLICATE = "ignored_duplicate"
WEBHOOK_OUTCOME_IGNORED_EVENT = "ignored_event"
WEBHOOK_OUTCOME_IGNORED_NO_TXN = "ignored_no_txn"
WEBHOOK_OUTCOME_REJECTED_IP = "rejected_ip"
WEBHOOK_OUTCOME_REJECTED_INVALID_BODY = "rejected_invalid_body"
WEBHOOK_OUTCOME_REJECTED_VALIDATION = "rejected_validation"
WEBHOOK_OUTCOME_REJECTED_AMOUNT_MISMATCH = "rejected_amount_mismatch"
WEBHOOK_OUTCOME_API_VERIFY_FAILED = "api_verify_failed"


def _log_webhook_outcome(
    outcome: str,
    *,
    event: str | None = None,
    payment_id: str | None = None,
    txn_id: int | None = None,
    user_id: int | None = None,
    ip_check: bool | None = None,
    api_status: str | None = None,
    amount_match: bool | None = None,
) -> None:
    """Структурированный лог результата обработки webhook (без секретов и PII в значениях)."""
    extra: dict[str, str | int | bool | None] = {
        "yookassa_webhook_outcome": outcome,
        "yookassa_event": event,
        "yookassa_payment_id": payment_id,
        "txn_id": txn_id,
        "user_id": user_id,
        "ip_check": ip_check,
        "api_status": api_status,
        "amount_match": amount_match,
    }
    logger.info(
        "YooKassa webhook outcome=%s event=%s payment_id=%s",
        outcome, event, payment_id,
        extra={k: v for k, v in extra.items() if v is not None},
    )


YOOKASSA_IPS = [
    ipaddress.ip_network("185.71.76.0/27"),
    ipaddress.ip_network("185.71.77.0/27"),
    ipaddress.ip_network("77.75.153.0/25"),
    ipaddress.ip_network("77.75.156.11/32"),
    ipaddress.ip_network("77.75.156.35/32"),
    ipaddress.ip_network("77.75.154.128/25"),
    ipaddress.ip_network("2a02:5180::/32"),
]

# Заголовки реального IP читаем только если peer — доверенный прокси.
# Это снижает риск spoofing через X-Real-IP/X-Forwarded-For.
TRUSTED_PROXY_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
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


def _is_trusted_proxy_ip(ip_str: str | None) -> bool:
    """Проверяет, что peer IP относится к доверенному proxy/network."""
    if not ip_str or not isinstance(ip_str, str):
        return False
    try:
        ip = ipaddress.ip_address(ip_str.strip())
        return any(ip in net for net in TRUSTED_PROXY_NETS)
    except ValueError:
        return False


def _extract_effective_client_ip(request: web.Request) -> str | None:
    """
    Возвращает IP клиента для валидации:
    - если peer IP уже из сетей ЮKassa — берём его;
    - если peer — доверенный прокси, берём X-Real-IP или первый IP из X-Forwarded-For;
    - иначе используем только peer IP.
    """
    peer_ip = getattr(request, "remote", None)
    if _is_valid_yookassa_ip(peer_ip):
        return peer_ip
    if not _is_trusted_proxy_ip(peer_ip):
        return peer_ip

    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return x_real_ip.strip()

    xff = request.headers.get("X-Forwarded-For")
    if xff:
        first_ip = xff.split(",", 1)[0].strip()
        if first_ip:
            return first_ip
    return peer_ip


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

    client_ip = _extract_effective_client_ip(request)
    if not _is_valid_yookassa_ip(client_ip):
        settings = get_settings()
        if "ngrok" not in (settings.WEBHOOK_HOST or ""):
            _log_webhook_outcome(WEBHOOK_OUTCOME_REJECTED_IP, ip_check=False)
            logger.warning("Webhook from invalid IP: %s", client_ip)
            return web.Response(status=403)

    try:
        body = await request.json()
    except Exception as e:
        _log_webhook_outcome(WEBHOOK_OUTCOME_REJECTED_INVALID_BODY)
        logger.warning("Invalid webhook body: %s", e)
        return web.Response(status=400)

    event = body.get("event") if isinstance(body, dict) else None

    # refund.succeeded — идемпотентная обработка (лог + запись в refunds_processed)
    if event == "refund.succeeded":
        try:
            refund_payload = YooKassaRefundWebhookPayload.model_validate(body)
        except (ValidationError, Exception):
            _log_webhook_outcome(WEBHOOK_OUTCOME_REJECTED_VALIDATION, event=event)
            return web.Response(status=400)
        refund_id = refund_payload.object.id
        payment_id_refund = refund_payload.object.payment_id
        if not refund_id:
            _log_webhook_outcome(WEBHOOK_OUTCOME_IGNORED_EVENT, event=event)
            return web.Response(status=200, text="ok")
        if async_session_factory is None:
            return web.Response(status=500)
        async with async_session_factory() as session:
            existing = await session.execute(
                select(RefundProcessed).where(RefundProcessed.refund_id == refund_id)
            )
            if existing.scalar_one_or_none():
                _log_webhook_outcome(
                    WEBHOOK_OUTCOME_IGNORED_DUPLICATE,
                    event=event,
                    payment_id=payment_id_refund,
                )
                return web.Response(status=200, text="ok")
            session.add(
                RefundProcessed(refund_id=refund_id, payment_id=payment_id_refund)
            )
            await session.commit()
        _log_webhook_outcome(
            WEBHOOK_OUTCOME_ACCEPTED,
            event=event,
            payment_id=payment_id_refund,
            ip_check=True,
        )
        logger.info("Refund %s (payment %s) recorded for moderation", refund_id, payment_id_refund)
        return web.Response(status=200, text="ok")

    try:
        payload = YooKassaWebhookPayload.model_validate(body)
    except ValidationError as e:
        _log_webhook_outcome(
            WEBHOOK_OUTCOME_REJECTED_VALIDATION,
            event=event,
        )
        logger.warning("Webhook payload validation failed: %s", e)
        return web.Response(status=400)

    event = payload.event
    obj = payload.object
    metadata = obj.metadata or {}
    if event not in ("payment.succeeded", "payment.canceled"):
        _log_webhook_outcome(WEBHOOK_OUTCOME_IGNORED_EVENT, event=event, payment_id=obj.id or None)
        return web.Response(status=200, text="ok")

    payment_id = obj.id
    status = obj.status
    if not payment_id:
        _log_webhook_outcome(WEBHOOK_OUTCOME_IGNORED_EVENT, event=event)
        return web.Response(status=200, text="ok")

    if async_session_factory is None:
        _log_webhook_outcome(WEBHOOK_OUTCOME_API_VERIFY_FAILED, event=event, payment_id=payment_id)
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
            _log_webhook_outcome(
                WEBHOOK_OUTCOME_IGNORED_NO_TXN,
                event=event,
                payment_id=payment_id,
            )
            logger.warning("Transaction not found for payment %s", payment_id)
            return web.Response(status=200, text="ok")

        if txn.status in ("succeeded", "canceled"):
            _log_webhook_outcome(
                WEBHOOK_OUTCOME_IGNORED_DUPLICATE,
                event=event,
                payment_id=payment_id,
                txn_id=txn.id,
                user_id=txn.user_id,
            )
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
            _log_webhook_outcome(
                WEBHOOK_OUTCOME_ACCEPTED,
                event=event,
                payment_id=payment_id,
                txn_id=txn.id,
                user_id=user_id,
                ip_check=True,
            )
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
            _log_webhook_outcome(
                WEBHOOK_OUTCOME_API_VERIFY_FAILED,
                event=event,
                payment_id=payment_id,
                txn_id=txn.id,
                user_id=user_id,
                ip_check=True,
            )
            logger.warning("get_payment_status failed for %s: %s", payment_id, e)
            return web.Response(status=500)

        api_status = payment_data.get("status")
        if api_status != "succeeded":
            _log_webhook_outcome(
                WEBHOOK_OUTCOME_API_VERIFY_FAILED,
                event=event,
                payment_id=payment_id,
                txn_id=txn.id,
                user_id=user_id,
                ip_check=True,
                api_status=api_status,
            )
            logger.warning("Payment %s API status is %s, not succeeded", payment_id, api_status)
            return web.Response(status=200, text="ok")

        api_amount = payment_data.get("amount", {})
        api_value = api_amount.get("value") if isinstance(api_amount, dict) else None
        amount_ok = _amount_matches(api_value, txn.amount)
        if not amount_ok:
            _log_webhook_outcome(
                WEBHOOK_OUTCOME_REJECTED_AMOUNT_MISMATCH,
                event=event,
                payment_id=payment_id,
                txn_id=txn.id,
                user_id=user_id,
                ip_check=True,
                api_status=api_status,
                amount_match=False,
            )
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
            _log_webhook_outcome(
                WEBHOOK_OUTCOME_API_VERIFY_FAILED,
                event=event,
                payment_id=payment_id,
                txn_id=txn.id,
                user_id=user_id,
                ip_check=True,
                api_status=api_status,
                amount_match=True,
            )
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
        _log_webhook_outcome(
            WEBHOOK_OUTCOME_ACCEPTED,
            event=event,
            payment_id=payment_id,
            txn_id=txn.id,
            user_id=user_id,
            ip_check=True,
            api_status=api_status,
            amount_match=True,
        )
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

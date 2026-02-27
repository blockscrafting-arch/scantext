"""
ЮKassa: создание платежа и валидация webhook.
"""
from __future__ import annotations

import asyncio
import uuid
import logging
from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator

from config import get_settings

logger = logging.getLogger(__name__)


class PaymentCreateRequest(BaseModel):
    """Запрос на создание платежа."""
    amount: str = Field(..., description="Сумма, например 100.00")
    currency: str = Field(default="RUB")
    description: str | None = None
    user_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaymentCreateResponse(BaseModel):
    """Ответ с ссылкой на оплату."""
    id: str
    status: str
    confirmation_url: str | None = None
    amount: str
    currency: str
    description: str | None = None


async def create_payment(
    amount: str,
    description: str = "",
    metadata: dict | None = None,
    idempotence_key: str | None = None,
) -> PaymentCreateResponse:
    """
    Создаёт платёж в ЮKassa, возвращает confirmation_url для редиректа пользователя.
    Асинхронный вызов.
    """
    settings = get_settings()
    url = "https://api.yookassa.ru/v3/payments"
    auth = (settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY)
    idempotence_key = idempotence_key or str(uuid.uuid4())
    payload = {
        "amount": {"value": amount, "currency": "RUB"},
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": settings.YOOKASSA_RETURN_URL,
        },
        "description": description or "Оплата лимитов",
        "metadata": metadata or {},
    }
    headers = {"Idempotence-Key": idempotence_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, json=payload, auth=auth, headers=headers)
        if r.status_code == 500:
            await asyncio.sleep(1.5)
            r = await client.post(url, json=payload, auth=auth, headers=headers)
        r.raise_for_status()
        data = r.json()

    conf = data.get("confirmation", {})
    return PaymentCreateResponse(
        id=data["id"],
        status=data.get("status", ""),
        confirmation_url=conf.get("confirmation_url"),
        amount=data.get("amount", {}).get("value", amount),
        currency=data.get("amount", {}).get("currency", "RUB"),
        description=data.get("description"),
    )


async def get_payment_status(payment_id: str) -> dict[str, Any]:
    """Получает текущий статус платежа из API ЮKassa."""
    settings = get_settings()
    url = f"https://api.yookassa.ru/v3/payments/{payment_id}"
    auth = (settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY)
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, auth=auth)
        r.raise_for_status()
        return r.json()


# --- Модели для валидации webhook ЮKassa ---


class YooKassaPaymentObjectAmount(BaseModel):
    """Сумма из объекта платежа в уведомлении."""
    value: str
    currency: str = "RUB"


class YooKassaPaymentObject(BaseModel):
    """Объект payment в теле уведомления."""

    id: str
    status: str
    metadata: dict[str, Any] | None = None
    amount: YooKassaPaymentObjectAmount | None = None

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id_to_str(cls, v: Any) -> str:
        """ЮKassa может вернуть id числом; приводим к строке."""
        if v is None:
            return ""
        s = str(v).strip()
        return s if s else ""


class YooKassaWebhookPayload(BaseModel):
    """Тело POST-запроса уведомления ЮKassa (платёж)."""
    type: str = "notification"
    event: str
    object: YooKassaPaymentObject


# --- Модели для уведомления refund.succeeded ---


class YooKassaRefundAmount(BaseModel):
    """Сумма возврата."""
    value: str
    currency: str = "RUB"


class YooKassaRefundObject(BaseModel):
    """Объект refund в теле уведомления refund.succeeded."""

    id: str
    payment_id: str
    status: str
    amount: YooKassaRefundAmount | None = None

    @field_validator("id", "payment_id", mode="before")
    @classmethod
    def coerce_to_str(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip() or ""


class YooKassaRefundWebhookPayload(BaseModel):
    """Тело POST-запроса уведомления ЮKassa (возврат)."""
    type: str = "notification"
    event: str = "refund.succeeded"
    object: YooKassaRefundObject

"""
Обработанные возвраты ЮKassa (идемпотентность webhook refund.succeeded).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RefundProcessed(Base):
    """Факт обработки уведомления refund.succeeded (один раз на refund_id)."""

    __tablename__ = "refunds_processed"

    refund_id: Mapped[str] = mapped_column(String(255), primary_key=True)  # id из ЮKassa
    payment_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

"""
Платёжные транзакции (ЮKassa).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Transaction(Base):
    """Платёж ЮKassa."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    yookassa_payment_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="RUB", nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # pending, succeeded, canceled, etc.
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Снимок пакета на момент покупки (для начисления по webhook)
    package_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    package_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    package_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    package_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="transactions")

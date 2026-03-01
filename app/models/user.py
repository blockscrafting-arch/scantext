"""
Модели пользователя, баланса и UTM-меток.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.transaction import Transaction


class User(Base):
    """Пользователь Telegram."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 152-ФЗ: согласие с политикой конфиденциальности
    is_agreed_to_policy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    policy_agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Блокировка (админка)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    # Динамические права администратора
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    # Бесплатные лимиты (сгораемые за период)
    free_limits_remaining: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    free_limits_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    balance: Mapped["UserBalance"] = relationship("UserBalance", back_populates="user", uselist=False)
    utm_records: Mapped[list["UserUTM"]] = relationship("UserUTM", back_populates="user")
    documents: Mapped[list["Document"]] = relationship("Document", back_populates="user")
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="user")


class UserBalance(Base):
    """Купленные лимиты (не сгорают)."""

    __tablename__ = "user_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    purchased_credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="balance")


class UserUTM(Base):
    """UTM-метки (deep link при /start)."""

    __tablename__ = "user_utm"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    utm_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_term: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_content: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_start_payload: Mapped[str | None] = mapped_column(Text, nullable=True)  # полная строка после /start
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="utm_records")

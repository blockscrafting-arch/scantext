"""
Обрабатываемые документы (PDF/фото).
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Document(Base):
    """Документ: загруженный файл, статус обработки. Результат отправляется в чат (текст или файл)."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    telegram_file_id: Mapped[str] = mapped_column(String(512), nullable=False)  # file_id из Telegram
    telegram_file_unique_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Статус: pending, processing, done, error
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    deducted_free: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    deducted_paid: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    # Результат (mime типа результата; раньше был result_s3_key — колонка оставлена для совместимости БД)
    result_s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    result_mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)

    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="documents")

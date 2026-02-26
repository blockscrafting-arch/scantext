"""
Модель динамических настроек бота (переопределение .env).
"""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BotSettings(Base):
    """Ключ-значение настроек (переопределяют config из .env)."""

    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)

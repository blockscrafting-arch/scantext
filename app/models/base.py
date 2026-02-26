"""Базовый класс для всех моделей."""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base для моделей."""

    pass

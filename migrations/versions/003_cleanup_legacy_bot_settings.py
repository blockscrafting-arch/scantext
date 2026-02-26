"""cleanup legacy OCR/Tesseract keys from bot_settings

Revision ID: 003
Revises: 002
Create Date: 2026-02-22

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_KEYS = (
    "OCR_CONTRAST",
    "TESSERACT_TIMEOUT",
    "TESSERACT_CONFIG",
    "OCR_MIN_SIDE",
    "OCR_BINARIZE",
    "TESSERACT_CMD",
)


def upgrade() -> None:
    conn = op.get_bind()
    for key in LEGACY_KEYS:
        conn.execute(text("DELETE FROM bot_settings WHERE key = :key"), {"key": key})


def downgrade() -> None:
    # Не восстанавливаем удалённые ключи — значения неизвестны.
    pass

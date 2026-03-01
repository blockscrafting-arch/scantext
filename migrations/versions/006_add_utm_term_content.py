"""Add utm_term and utm_content to user_utm

Revision ID: 006
Revises: 005
Create Date: 2026-03-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_utm", sa.Column("utm_term", sa.String(255), nullable=True))
    op.add_column("user_utm", sa.Column("utm_content", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("user_utm", "utm_content")
    op.drop_column("user_utm", "utm_term")

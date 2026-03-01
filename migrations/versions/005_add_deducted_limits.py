"""Add deducted_free and deducted_paid to documents

Revision ID: 005
Revises: 004
Create Date: 2026-03-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("deducted_free", sa.Integer(), server_default="0", nullable=False))
    op.add_column("documents", sa.Column("deducted_paid", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("documents", "deducted_paid")
    op.drop_column("documents", "deducted_free")

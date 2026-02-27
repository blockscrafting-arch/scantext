"""refunds_processed table for refund.succeeded idempotency

Revision ID: 004
Revises: f57ca9300786
Create Date: 2026-02-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "004"
down_revision: Union[str, None] = "f57ca9300786"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "refunds_processed",
        sa.Column("refund_id", sa.String(255), nullable=False),
        sa.Column("payment_id", sa.String(255), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("refund_id"),
    )
    op.create_index(op.f("ix_refunds_processed_payment_id"), "refunds_processed", ["payment_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_refunds_processed_payment_id"), table_name="refunds_processed")
    op.drop_table("refunds_processed")

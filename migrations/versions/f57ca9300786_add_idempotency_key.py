"""add idempotency_key

Revision ID: f57ca9300786
Revises: 04f63b823504
Create Date: 2026-02-23 10:03:22.650118

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f57ca9300786'
down_revision: Union[str, Sequence[str], None] = '04f63b823504'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('transactions', sa.Column('idempotency_key', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_transactions_idempotency_key'), 'transactions', ['idempotency_key'], unique=True)
    op.alter_column('transactions', 'yookassa_payment_id',
               existing_type=sa.VARCHAR(length=255),
               nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('transactions', 'yookassa_payment_id',
               existing_type=sa.VARCHAR(length=255),
               nullable=False)
    op.drop_index(op.f('ix_transactions_idempotency_key'), table_name='transactions')
    op.drop_column('transactions', 'idempotency_key')

"""payment_packages and transaction package snapshot

Revision ID: 007
Revises: 006
Create Date: 2026-03-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_packages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="RUB"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payment_packages_code"), "payment_packages", ["code"], unique=True)

    op.add_column("transactions", sa.Column("package_code", sa.String(64), nullable=True))
    op.add_column("transactions", sa.Column("package_name", sa.String(128), nullable=True))
    op.add_column("transactions", sa.Column("package_pages", sa.Integer(), nullable=True))
    op.add_column("transactions", sa.Column("package_price", sa.Numeric(10, 2), nullable=True))

    # Seed 3 тарифов только при пустой таблице (идемпотентный upgrade)
    op.execute(
        sa.text("""
            INSERT INTO payment_packages (code, name, pages, price, currency, is_active, sort_order)
            SELECT 'demo', 'Демо', 50, 225.00, 'RUB', true, 1
            WHERE NOT EXISTS (SELECT 1 FROM payment_packages LIMIT 1)
            UNION ALL
            SELECT 'basic', 'Базовый', 300, 900.00, 'RUB', true, 2
            WHERE NOT EXISTS (SELECT 1 FROM payment_packages LIMIT 1)
            UNION ALL
            SELECT 'pro', 'Про', 1000, 2900.00, 'RUB', true, 3
            WHERE NOT EXISTS (SELECT 1 FROM payment_packages LIMIT 1)
        """)
    )


def downgrade() -> None:
    op.drop_column("transactions", "package_price")
    op.drop_column("transactions", "package_pages")
    op.drop_column("transactions", "package_name")
    op.drop_column("transactions", "package_code")
    op.drop_index(op.f("ix_payment_packages_code"), table_name="payment_packages")
    op.drop_table("payment_packages")

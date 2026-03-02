"""payment_packages CHECK constraints (pages > 0, price > 0)

Revision ID: 008
Revises: 007
Create Date: 2026-03-02

"""
from typing import Sequence, Union

from alembic import op


revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "chk_payment_packages_pages_positive",
        "payment_packages",
        "pages > 0",
    )
    op.create_check_constraint(
        "chk_payment_packages_price_positive",
        "payment_packages",
        "price > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "chk_payment_packages_price_positive",
        "payment_packages",
        type_="check",
    )
    op.drop_constraint(
        "chk_payment_packages_pages_positive",
        "payment_packages",
        type_="check",
    )

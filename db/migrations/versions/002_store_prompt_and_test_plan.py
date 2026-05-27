"""Store original prompt and full generated test plan.

Revision ID: 002_prompt_plan
Revises: 001_initial
Create Date: 2026-05-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "002_prompt_plan"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("test_cases", sa.Column("user_prompt", sa.Text(), nullable=True))
    op.add_column(
        "test_cases",
        sa.Column(
            "test_plan",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("test_cases", "test_plan")
    op.drop_column("test_cases", "user_prompt")

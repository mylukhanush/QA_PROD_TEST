"""Add duration_ms column to run_steps table.

Revision ID: 003_add_duration_ms
Revises: 002_prompt_plan
Create Date: 2026-05-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003_add_duration_ms"
down_revision: Union[str, None] = "002_prompt_plan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("run_steps", sa.Column("duration_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("run_steps", "duration_ms")

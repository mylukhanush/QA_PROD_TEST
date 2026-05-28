"""Add kpi_download_history table.

Revision ID: 005_kpi_download_history
Revises: 004_suites_and_runs
Create Date: 2026-05-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '005_kpi_download_history'
down_revision: Union[str, None] = '004_suites_and_runs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == 'sqlite'
    inspector = sa.inspect(bind)
    
    uuid_type = sa.String(36) if is_sqlite else postgresql.UUID(as_uuid=True)
    tables = inspector.get_table_names()

    if 'kpi_download_history' not in tables:
        op.create_table(
            'kpi_download_history',
            sa.Column('id', uuid_type, primary_key=True),
            sa.Column('run_id', uuid_type, sa.ForeignKey('test_runs.id'), nullable=False),
            sa.Column('site_name', sa.String(50), nullable=False),
            sa.Column('filename', sa.String(255), nullable=False),
            sa.Column('downloaded_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if 'kpi_download_history' in tables:
        op.drop_table('kpi_download_history')

"""Add test_suites, suite_runs, suite_test_cases tables and suite_run_id to test_runs.

Revision ID: 004_suites_and_runs
Revises: 003_add_duration_ms
Create Date: 2026-05-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '004_suites_and_runs'
down_revision: Union[str, None] = '003_add_duration_ms'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == 'sqlite'
    inspector = sa.inspect(bind)
    
    uuid_type = sa.String(36) if is_sqlite else postgresql.UUID(as_uuid=True)
    tables = inspector.get_table_names()

    # 1. Create test_suites table if it does not exist
    if 'test_suites' not in tables:
        op.create_table(
            'test_suites',
            sa.Column('id', uuid_type, primary_key=True),
            sa.Column('name', sa.String(255), unique=True, nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    # 2. Create suite_runs table if it does not exist
    if 'suite_runs' not in tables:
        op.create_table(
            'suite_runs',
            sa.Column('id', uuid_type, primary_key=True),
            sa.Column('suite_id', uuid_type, sa.ForeignKey('test_suites.id'), nullable=False),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, server_default='queued'),
            sa.Column('duration_ms', sa.Integer(), nullable=True),
        )

    # 3. Create suite_test_cases association table if it does not exist
    if 'suite_test_cases' not in tables:
        op.create_table(
            'suite_test_cases',
            sa.Column('suite_id', uuid_type, sa.ForeignKey('test_suites.id'), primary_key=True),
            sa.Column('test_case_id', uuid_type, sa.ForeignKey('test_cases.id'), primary_key=True),
        )

    # 4. Add suite_run_id column to test_runs if it does not exist
    test_runs_columns = [col['name'] for col in inspector.get_columns('test_runs')]
    if 'suite_run_id' not in test_runs_columns:
        op.add_column('test_runs', sa.Column('suite_run_id', uuid_type, sa.ForeignKey('suite_runs.id'), nullable=True))

    # 5. Add name column to test_cases if it does not exist
    test_cases_columns = [col['name'] for col in inspector.get_columns('test_cases')]
    if 'name' not in test_cases_columns:
        op.add_column('test_cases', sa.Column('name', sa.String(255), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    # Drop columns
    if 'test_runs' in tables:
        test_runs_columns = [col['name'] for col in inspector.get_columns('test_runs')]
        if 'suite_run_id' in test_runs_columns:
            op.drop_column('test_runs', 'suite_run_id')

    if 'test_cases' in tables:
        test_cases_columns = [col['name'] for col in inspector.get_columns('test_cases')]
        if 'name' in test_cases_columns:
            op.drop_column('test_cases', 'name')

    # Drop tables
    if 'suite_test_cases' in tables:
        op.drop_table('suite_test_cases')
    if 'suite_runs' in tables:
        op.drop_table('suite_runs')
    if 'test_suites' in tables:
        op.drop_table('test_suites')

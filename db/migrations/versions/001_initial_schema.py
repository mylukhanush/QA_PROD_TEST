"""Initial schema — all 6 tables.

Revision ID: 001_initial
Revises: 
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == 'sqlite'
    
    uuid_type = sa.String(36) if is_sqlite else postgresql.UUID(as_uuid=True)
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

    # sites
    op.create_table(
        'sites',
        sa.Column('id', uuid_type, primary_key=True),
        sa.Column('name', sa.String(20), unique=True, nullable=False),
        sa.Column('base_url', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # site_elements (shared — no site_id)
    op.create_table(
        'site_elements',
        sa.Column('id', uuid_type, primary_key=True),
        sa.Column('page', sa.String(100), nullable=False),
        sa.Column('section', sa.String(100), nullable=False),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('selector', sa.String(500), nullable=False),
        sa.Column('element_type', sa.String(50), nullable=False),
        sa.Column('is_dynamic', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('value_sample', sa.String(500), nullable=True),
        sa.Column('last_crawled_at', sa.DateTime(timezone=True), nullable=True),
    )

    # test_cases (universal — no site_id)
    op.create_table(
        'test_cases',
        sa.Column('id', uuid_type, primary_key=True),
        sa.Column('situation_description', sa.Text(), nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('steps', json_type, nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    )

    # test_runs
    op.create_table(
        'test_runs',
        sa.Column('id', uuid_type, primary_key=True),
        sa.Column('test_case_id', uuid_type, sa.ForeignKey('test_cases.id'), nullable=False),
        sa.Column('site_id', uuid_type, sa.ForeignKey('sites.id'), nullable=False),
        sa.Column('triggered_by', sa.String(10), nullable=False, server_default='web'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='running'),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('report_path', sa.String(500), nullable=True),
    )

    # run_steps
    op.create_table(
        'run_steps',
        sa.Column('id', uuid_type, primary_key=True),
        sa.Column('run_id', uuid_type, sa.ForeignKey('test_runs.id'), nullable=False),
        sa.Column('step_order', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='running'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('screenshot_path', sa.String(500), nullable=True),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
    )

    # value_captures
    op.create_table(
        'value_captures',
        sa.Column('id', uuid_type, primary_key=True),
        sa.Column('run_id', uuid_type, sa.ForeignKey('test_runs.id'), nullable=False),
        sa.Column('site_id', uuid_type, sa.ForeignKey('sites.id'), nullable=False),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('page', sa.String(100), nullable=False),
        sa.Column('selector', sa.String(500), nullable=False),
        sa.Column('captured_value', sa.String(500), nullable=False),
        sa.Column('expected_value', sa.String(500), nullable=True),
        sa.Column('matched', sa.Boolean(), nullable=True),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Indexes for common queries
    op.create_index('ix_test_runs_site_id', 'test_runs', ['site_id'])
    op.create_index('ix_test_runs_test_case_id', 'test_runs', ['test_case_id'])
    op.create_index('ix_test_runs_status', 'test_runs', ['status'])
    op.create_index('ix_run_steps_run_id', 'run_steps', ['run_id'])
    op.create_index('ix_value_captures_run_id', 'value_captures', ['run_id'])
    op.create_index('ix_value_captures_site_id', 'value_captures', ['site_id'])
    op.create_index('ix_value_captures_label', 'value_captures', ['label'])
    op.create_index('ix_site_elements_page', 'site_elements', ['page'])


def downgrade() -> None:
    op.drop_table('value_captures')
    op.drop_table('run_steps')
    op.drop_table('test_runs')
    op.drop_table('test_cases')
    op.drop_table('site_elements')
    op.drop_table('sites')

"""add dashboard login: employee email/password/role + dashboard_sessions

Revision ID: c4d5e6f7a8b9
Revises: a1b2c3d4e5f6
Create Date: 2026-09-28 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: str | Sequence[str] | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('employees') as batch:
        batch.add_column(sa.Column('email', sa.String(), nullable=True))
        batch.add_column(sa.Column('password_hash', sa.String(), nullable=True))
        batch.add_column(sa.Column('role', sa.String(), server_default='employee', nullable=False))
        batch.create_unique_constraint('uq_employees_email', ['email'])

    op.create_table(
        'dashboard_sessions',
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('token_hash', sa.String(), nullable=False),
        sa.Column('employee_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('expires_at', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.employee_id']),
        sa.PrimaryKeyConstraint('session_id'),
    )
    op.create_index('ix_dashboard_sessions_token_hash', 'dashboard_sessions', ['token_hash'], unique=True)
    op.create_index('ix_dashboard_sessions_employee_id', 'dashboard_sessions', ['employee_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_dashboard_sessions_employee_id', table_name='dashboard_sessions')
    op.drop_index('ix_dashboard_sessions_token_hash', table_name='dashboard_sessions')
    op.drop_table('dashboard_sessions')
    with op.batch_alter_table('employees') as batch:
        batch.drop_constraint('uq_employees_email', type_='unique')
        batch.drop_column('role')
        batch.drop_column('password_hash')
        batch.drop_column('email')

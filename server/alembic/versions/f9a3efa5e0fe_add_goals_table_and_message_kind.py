"""add goals table and message kind

Revision ID: f9a3efa5e0fe
Revises: d196cab5965b
Create Date: 2026-08-28 13:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f9a3efa5e0fe'
down_revision: str | Sequence[str] | None = 'd196cab5965b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('goals',
    sa.Column('goal_id', sa.String(), nullable=False),
    sa.Column('employee_id', sa.String(), nullable=False),
    sa.Column('text', sa.String(), nullable=False),
    sa.Column('deadline_at', sa.Float(), nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.employee_id'], ),
    sa.PrimaryKeyConstraint('goal_id')
    )
    op.create_index('ix_goals_employee_id_created_at', 'goals', ['employee_id', 'created_at'], unique=False)
    op.add_column('messages', sa.Column('kind', sa.String(), nullable=False, server_default='break'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('messages', 'kind')
    op.drop_index('ix_goals_employee_id_created_at', table_name='goals')
    op.drop_table('goals')

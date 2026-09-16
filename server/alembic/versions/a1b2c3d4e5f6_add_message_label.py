"""add message label

Revision ID: a1b2c3d4e5f6
Revises: f9a3efa5e0fe
Create Date: 2026-09-15 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | Sequence[str] | None = 'f9a3efa5e0fe'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('messages', sa.Column('label', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('messages', 'label')

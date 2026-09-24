"""add column_labels for user column renaming

Revision ID: 3dc8868a80af
Revises: 5711d8c26791
Create Date: 2026-09-21 14:10:37.409907
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '3dc8868a80af'
down_revision: str | None = '5711d8c26791'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default backfills existing rows; the app-level default doesn't apply retroactively.
    op.add_column(
        'import_requests',
        sa.Column('column_labels', sa.JSON(), nullable=False, server_default='{}'),
    )


def downgrade() -> None:
    op.drop_column('import_requests', 'column_labels')

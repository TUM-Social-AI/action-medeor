"""add raw_file, available_columns, custom_columns for post-hoc custom column extraction

Revision ID: 9a1f3c7d5e2b
Revises: 3dc8868a80af
Create Date: 2026-09-21 15:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '9a1f3c7d5e2b'
down_revision: str | None = '3dc8868a80af'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default backfills existing rows; the app-level default doesn't apply retroactively.
    op.add_column(
        'import_requests',
        sa.Column('available_columns', sa.JSON(), nullable=False, server_default='[]'),
    )
    op.add_column(
        'import_requests',
        sa.Column('custom_columns', sa.JSON(), nullable=False, server_default='[]'),
    )
    # No server_default: existing rows simply have no stored source file (NULL), which
    # add_custom_column() treats as "can't re-extract, ask the user to re-upload".
    op.add_column(
        'import_requests',
        sa.Column('raw_file', sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('import_requests', 'raw_file')
    op.drop_column('import_requests', 'custom_columns')
    op.drop_column('import_requests', 'available_columns')

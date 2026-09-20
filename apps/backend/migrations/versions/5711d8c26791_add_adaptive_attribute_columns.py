"""add adaptive attribute columns

Revision ID: 5711d8c26791
Revises: f5aa70577161
Create Date: 2026-09-20 18:35:06.967413
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '5711d8c26791'
down_revision: str | None = 'f5aa70577161'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default backfills existing rows; the app-level default doesn't apply retroactively.
    op.add_column(
        "import_requests",
        sa.Column("attribute_columns", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "request_items",
        sa.Column("attributes", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("request_items", "attributes")
    op.drop_column("import_requests", "attribute_columns")

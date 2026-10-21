"""Persist the worksheets selected before extraction."""

import sqlalchemy as sa
from alembic import op

revision = "20261021_0001"
down_revision = "20261012_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "import_requests",
        sa.Column("selected_sheets", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("import_requests", "selected_sheets")

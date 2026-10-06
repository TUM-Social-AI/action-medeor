"""Persist validated request table layouts for subsequent custom-column extraction."""

import sqlalchemy as sa
from alembic import op

revision = "20261006_0001"
down_revision = "20261005_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "import_requests",
        sa.Column("table_mappings", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("import_requests", "table_mappings")

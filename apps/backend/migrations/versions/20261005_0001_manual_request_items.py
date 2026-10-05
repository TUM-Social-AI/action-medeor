"""Track manually entered request items separately from extracted rows."""

import sqlalchemy as sa
from alembic import op

revision = "20261005_0001"
down_revision = "20261002_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "request_items", sa.Column("manual", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    op.drop_column("request_items", "manual")

"""Live stage of uploads still being extracted, for an honest loading screen."""

import sqlalchemy as sa
from alembic import op

revision = "20261012_0002"
down_revision = "20261006_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_progress",
        sa.Column("token", sa.String(), primary_key=True),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False, server_default="basic"),
        sa.Column("items", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("import_progress")

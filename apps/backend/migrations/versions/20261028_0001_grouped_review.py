"""Grouped review, recoverable item removal, and atomic operation history."""

import sqlalchemy as sa
from alembic import op

revision = "20261028_0001"
down_revision = "20261022_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "import_requests",
        sa.Column("review_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    for column in (
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.Column("removed_by", sa.String()),
        sa.Column("source_key", sa.String()),
        sa.Column("source_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("field_reviews", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("review_findings", sa.JSON(), nullable=False, server_default="[]"),
    ):
        op.add_column("request_items", column)
    op.create_table(
        "request_review_issues",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "request_id",
            sa.String(),
            sa.ForeignKey("import_requests.request_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("request_items.id", ondelete="CASCADE"),
            index=True,
        ),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("resolution", sa.JSON()),
    )
    op.create_table(
        "request_review_operations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "request_id",
            sa.String(),
            sa.ForeignKey("import_requests.request_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("undone_by", sa.String()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade():
    op.drop_table("request_review_operations")
    op.drop_table("request_review_issues")
    for name in (
        "review_findings",
        "field_reviews",
        "source_active",
        "source_key",
        "removed_by",
        "removed_at",
    ):
        op.drop_column("request_items", name)
    op.drop_column("import_requests", "review_revision")

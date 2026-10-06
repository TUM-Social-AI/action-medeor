"""AI review preferences, provenance and cached results.

Revision ID: 20261006_0002
Revises: 20261006_0001
"""

import sqlalchemy as sa
from alembic import op

revision = "20261006_0002"
down_revision = "20261006_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_extraction_preferences",
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("mode", sa.String(), nullable=False),
    )
    op.add_column(
        "import_requests",
        sa.Column("extraction_mode", sa.String(), nullable=False, server_default="basic"),
    )
    op.add_column(
        "import_requests", sa.Column("ai_review", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column("request_items", sa.Column("verification_source", sa.String(), nullable=True))
    op.add_column(
        "request_items",
        sa.Column("inferred_fields", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "request_items", sa.Column("review_reasons", sa.JSON(), nullable=False, server_default="[]")
    )
    op.add_column("request_items", sa.Column("protected_fields", sa.JSON(), nullable=True))


def downgrade():
    for column in ("protected_fields", "review_reasons", "inferred_fields", "verification_source"):
        op.drop_column("request_items", column)
    op.drop_column("import_requests", "ai_review")
    op.drop_column("import_requests", "extraction_mode")
    op.drop_table("user_extraction_preferences")

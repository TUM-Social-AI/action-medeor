"""Persist request lifecycle and resumable matching work.

Revision ID: 20260925_0001
Revises: 9a1f3c7d5e2b
"""

import sqlalchemy as sa
from alembic import op

revision = "20260925_0001"
down_revision = "9a1f3c7d5e2b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("import_requests", sa.Column("workflow_status", sa.String(32), nullable=False, server_default="draft"))
    op.add_column("import_requests", sa.Column("catalog_snapshot_id", sa.Uuid(), nullable=True))
    op.execute("UPDATE import_requests SET workflow_status = 'review'")
    op.add_column("request_items", sa.Column("domain", sa.String(16), nullable=True))
    op.add_column("request_items", sa.Column("match_status", sa.String(16), nullable=False, server_default="pending"))
    op.add_column("request_items", sa.Column("match_error", sa.Text(), nullable=True))
    op.add_column("request_items", sa.Column("current_match_run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_request_item_match_run", "request_items", "match_runs", ["current_match_run_id"], ["id"], ondelete="SET NULL")
    op.create_table(
        "request_matching_jobs",
        sa.Column("request_id", sa.String(), sa.ForeignKey("import_requests.request_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("request_matching_jobs")
    op.drop_constraint("fk_request_item_match_run", "request_items", type_="foreignkey")
    op.drop_column("request_items", "current_match_run_id")
    op.drop_column("request_items", "match_error")
    op.drop_column("request_items", "match_status")
    op.drop_column("request_items", "domain")
    op.drop_column("import_requests", "catalog_snapshot_id")
    op.drop_column("import_requests", "workflow_status")

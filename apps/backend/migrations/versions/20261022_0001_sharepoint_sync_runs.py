"""Job-written SharePoint sync run status for catalogue polling."""

import sqlalchemy as sa
from alembic import op

revision = "20261022_0001"
down_revision = "20261021_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sharepoint_sync_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_name", sa.String(), nullable=False),
        sa.Column("execution_name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("message", sa.String(), nullable=True),
        sa.CheckConstraint("status IN ('running', 'completed', 'failed', 'skipped')",
                           name="ck_sharepoint_sync_runs_status"),
    )
    op.create_index("ix_sharepoint_sync_runs_recent", "sharepoint_sync_runs", ["job_name", "updated_at", "id"])
    op.create_index("ix_sharepoint_sync_runs_execution_name", "sharepoint_sync_runs", ["execution_name"])


def downgrade() -> None:
    op.drop_table("sharepoint_sync_runs")

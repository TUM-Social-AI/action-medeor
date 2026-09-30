"""Persist folder-scoped SharePoint sync state.

Revision ID: 20260929_0001
Revises: 20260928_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0001"
down_revision: str | None = "20260928_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sharepoint_sync_sources",
        sa.Column("drive_id", sa.String(1000), primary_key=True),
        sa.Column("folder_id", sa.String(1000), primary_key=True),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("delta_link", sa.Text()),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("mode IN ('delta', 'snapshot')", name="ck_sharepoint_sync_mode"),
    )
    op.create_table(
        "sharepoint_sync_items",
        sa.Column("drive_id", sa.String(1000), primary_key=True),
        sa.Column("folder_id", sa.String(1000), primary_key=True),
        sa.Column("item_id", sa.String(1000), primary_key=True),
        sa.Column("parent_id", sa.String(1000)),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("web_url", sa.Text()),
        sa.Column("etag", sa.Text()),
        sa.Column("ctag", sa.Text()),
        sa.Column("modified_at", sa.DateTime(timezone=True)),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("mime_type", sa.String(300)),
        sa.Column("is_folder", sa.Boolean(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pending_extraction", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_processed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["drive_id", "folder_id"],
            ["sharepoint_sync_sources.drive_id", "sharepoint_sync_sources.folder_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_sharepoint_sync_items_pending",
        "sharepoint_sync_items",
        ["drive_id", "folder_id", "pending_extraction", "is_deleted"],
    )


def downgrade() -> None:
    op.drop_table("sharepoint_sync_items")
    op.drop_table("sharepoint_sync_sources")

"""Add ERP catalog synchronization and versioned SharePoint offers.

Revision ID: 20260819_0002
Revises: 20260814_0001
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260819_0002"
down_revision: str | None = "20260814_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_imports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "article_source_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("source_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "translation_source_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("source_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "combined_source_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("source_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("article_checksum", sa.String(64), nullable=False),
        sa.Column("translation_checksum", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "article_checksum", "translation_checksum", name="uq_catalog_import_files"
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'completed_with_warnings', 'failed')",
            name="ck_catalog_import_status",
        ),
    )

    op.drop_constraint("ck_catalog_domain", "catalog_items", type_="check")
    op.create_check_constraint(
        "ck_catalog_domain",
        "catalog_items",
        "domain IN ('medicine', 'equipment', 'unknown')",
    )
    op.add_column(
        "catalog_items",
        sa.Column("matching_eligible", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "catalog_items",
        sa.Column("source_missing", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("catalog_items", sa.Column("last_seen_import_id", sa.Uuid()))
    op.add_column("catalog_items", sa.Column("missing_since_import_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_catalog_last_seen_import",
        "catalog_items",
        "catalog_imports",
        ["last_seen_import_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_catalog_missing_since_import",
        "catalog_items",
        "catalog_imports",
        ["missing_since_import_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_catalog_items_matching_state",
        "catalog_items",
        ["domain", "matching_eligible", "source_missing", "active"],
    )

    op.add_column(
        "catalog_item_versions",
        sa.Column("canonical_text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "catalog_item_versions",
        sa.Column("record_hash", sa.String(64), nullable=False, server_default=""),
    )

    op.create_table(
        "catalog_item_translations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "item_number",
            sa.String(100),
            sa.ForeignKey("catalog_items.item_number", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("source_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("raw_language_code", sa.String(20), nullable=False),
        sa.Column("locale", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("description_2", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "item_number",
            "source_snapshot_id",
            "raw_language_code",
            name="uq_catalog_translation_source",
        ),
    )
    op.create_index(
        "ix_catalog_item_translations_item_locale",
        "catalog_item_translations",
        ["item_number", "locale"],
    )

    op.add_column(
        "embedding_models",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_embedding_models_active", "embedding_models", ["active"])
    op.create_table(
        "catalog_embedding_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "catalog_item_version_id",
            sa.Uuid(),
            sa.ForeignKey("catalog_item_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_id",
            sa.String(300),
            sa.ForeignKey("embedding_models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "catalog_item_version_id", "model_id", name="uq_catalog_embedding_job"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_catalog_embedding_job_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_catalog_embedding_job_attempts"),
    )
    op.create_index(
        "ix_catalog_embedding_jobs_status", "catalog_embedding_jobs", ["model_id", "status"]
    )

    op.add_column("historical_offers", sa.Column("external_id", sa.String(1000)))
    op.add_column("historical_offers", sa.Column("external_version", sa.String(500)))
    op.add_column(
        "historical_offers",
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "historical_offers",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("historical_offers", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.add_column(
        "historical_offers",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.add_column(
        "historical_offers",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "uq_historical_offer_current_external_id",
        "historical_offers",
        ["external_id"],
        unique=True,
        postgresql_where=sa.text("is_current AND external_id IS NOT NULL"),
    )
    op.create_index(
        "ix_historical_offers_active_current",
        "historical_offers",
        ["active", "is_current"],
    )

    op.create_table(
        "sharepoint_offer_files",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("source_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(1000), nullable=False),
        sa.Column("external_version", sa.String(500), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(300)),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("modified_at", sa.DateTime(timezone=True)),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0", name="ck_sharepoint_offer_file_size"
        ),
    )
    op.create_index(
        "uq_sharepoint_offer_file_current_external_id",
        "sharepoint_offer_files",
        ["external_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "ix_sharepoint_offer_files_active_current",
        "sharepoint_offer_files",
        ["active", "is_current", "modified_at"],
    )


def downgrade() -> None:
    op.drop_table("sharepoint_offer_files")
    op.drop_index("ix_historical_offers_active_current", table_name="historical_offers")
    op.drop_index("uq_historical_offer_current_external_id", table_name="historical_offers")
    for column in (
        "updated_at",
        "created_at",
        "archived_at",
        "active",
        "is_current",
        "external_version",
        "external_id",
    ):
        op.drop_column("historical_offers", column)

    op.drop_table("catalog_embedding_jobs")
    op.drop_index("ix_embedding_models_active", table_name="embedding_models")
    op.drop_column("embedding_models", "active")
    op.drop_table("catalog_item_translations")
    op.drop_column("catalog_item_versions", "record_hash")
    op.drop_column("catalog_item_versions", "canonical_text")

    op.drop_index("ix_catalog_items_matching_state", table_name="catalog_items")
    op.drop_constraint("fk_catalog_missing_since_import", "catalog_items", type_="foreignkey")
    op.drop_constraint("fk_catalog_last_seen_import", "catalog_items", type_="foreignkey")
    op.drop_column("catalog_items", "missing_since_import_id")
    op.drop_column("catalog_items", "last_seen_import_id")
    op.drop_column("catalog_items", "source_missing")
    op.drop_column("catalog_items", "matching_eligible")
    op.drop_constraint("ck_catalog_domain", "catalog_items", type_="check")
    op.create_check_constraint(
        "ck_catalog_domain", "catalog_items", "domain IN ('medicine', 'equipment')"
    )
    op.drop_table("catalog_imports")

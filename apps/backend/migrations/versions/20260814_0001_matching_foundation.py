"""Create the matching persistence foundation with pgvector.

Revision ID: 20260814_0001
Revises:
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260814_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "source_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("document_id", sa.String(500), nullable=False),
        sa.Column("external_id", sa.String(1000)),
        sa.Column("uri", sa.Text()),
        sa.Column("checksum", sa.String(128)),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locator", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("source_type", "document_id", "checksum", name="uq_source_version"),
    )

    op.create_table(
        "catalog_items",
        sa.Column("item_number", sa.String(100), primary_key=True),
        sa.Column("domain", sa.String(30), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("quality_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.CheckConstraint("domain IN ('medicine', 'equipment')", name="ck_catalog_domain"),
    )
    op.create_index("ix_catalog_items_domain", "catalog_items", ["domain"])

    op.create_table(
        "catalog_item_versions",
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
        sa.Column("descriptions", postgresql.JSONB(), nullable=False),
        sa.Column("attributes", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("manufacturer", sa.Text()),
        sa.Column("brand", sa.Text()),
        sa.Column("family_id", sa.String(200)),
        sa.Column("package", postgresql.JSONB()),
        sa.Column("replenishment_method", sa.Text()),
        sa.Column("t1", sa.Boolean()),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "item_number", "source_snapshot_id", name="uq_catalog_item_source_version"
        ),
    )
    op.create_index(
        "ix_catalog_item_versions_item_time",
        "catalog_item_versions",
        ["item_number", "valid_from"],
    )
    op.create_index(
        "ix_catalog_item_versions_content_hash", "catalog_item_versions", ["content_hash"]
    )

    op.create_table(
        "inventory_snapshots",
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
        sa.Column("on_hand", sa.Numeric()),
        sa.Column("incoming_purchase_order", sa.Numeric()),
        sa.Column("purchasing_inquiry", sa.Numeric()),
        sa.Column("committed_order", sa.Numeric()),
        sa.Column("unit", sa.String(100)),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "item_number", "source_snapshot_id", name="uq_inventory_item_source_version"
        ),
        sa.CheckConstraint("on_hand IS NULL OR on_hand >= 0", name="ck_inventory_on_hand"),
        sa.CheckConstraint(
            "incoming_purchase_order IS NULL OR incoming_purchase_order >= 0",
            name="ck_inventory_incoming",
        ),
        sa.CheckConstraint(
            "purchasing_inquiry IS NULL OR purchasing_inquiry >= 0",
            name="ck_inventory_inquiry",
        ),
        sa.CheckConstraint(
            "committed_order IS NULL OR committed_order >= 0",
            name="ck_inventory_committed",
        ),
    )
    op.create_index(
        "ix_inventory_snapshots_item_time",
        "inventory_snapshots",
        ["item_number", "captured_at"],
    )

    op.create_table(
        "embedding_models",
        sa.Column("id", sa.String(300), primary_key=True),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("version", sa.String(200), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("distance_metric", sa.String(30), nullable=False, server_default="cosine"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("dimensions > 0", name="ck_embedding_dimensions"),
        sa.CheckConstraint("distance_metric = 'cosine'", name="ck_embedding_metric"),
    )

    op.execute(
        """
        CREATE TABLE product_embeddings (
            catalog_item_version_id UUID NOT NULL
                REFERENCES catalog_item_versions(id) ON DELETE CASCADE,
            model_id VARCHAR(300) NOT NULL
                REFERENCES embedding_models(id) ON DELETE RESTRICT,
            content_hash VARCHAR(64) NOT NULL,
            embedding vector NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (catalog_item_version_id, model_id)
        )
        """
    )
    op.create_index("ix_product_embeddings_model", "product_embeddings", ["model_id"])

    op.create_table(
        "historical_offers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("source_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("partner_id", sa.String(300)),
        sa.Column("destination_country", sa.String(200)),
        sa.Column("raw_request_text", sa.Text(), nullable=False),
        sa.Column(
            "item_number",
            sa.String(100),
            sa.ForeignKey("catalog_items.item_number", ondelete="SET NULL"),
        ),
        sa.Column("offered_description", sa.Text()),
        sa.Column("supplier", sa.String(500)),
        sa.Column("quantity", postgresql.JSONB()),
        sa.Column("package", postgresql.JSONB()),
        sa.Column("price", sa.Numeric()),
        sa.Column("currency", sa.String(10)),
        sa.Column("price_basis", sa.Text()),
        sa.Column("offer_date", sa.DateTime(timezone=True)),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.CheckConstraint("price IS NULL OR price >= 0", name="ck_historical_price"),
    )
    op.create_index("ix_historical_partner", "historical_offers", ["partner_id"])
    op.create_index("ix_historical_country", "historical_offers", ["destination_country"])
    op.create_index("ix_historical_item", "historical_offers", ["item_number"])

    op.create_table(
        "match_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("inquiry_id", sa.String(500), nullable=False),
        sa.Column("inquiry_line_id", sa.String(500), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("algorithm_version", sa.String(200), nullable=False),
        sa.Column("policy_version", sa.String(200), nullable=False),
        sa.Column("embedding_model_id", sa.String(300)),
        sa.Column("request_payload", postgresql.JSONB(), nullable=False),
        sa.Column("source_versions", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("result_payload", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name="ck_match_run_status"
        ),
    )
    op.create_index("ix_match_runs_inquiry", "match_runs", ["inquiry_id", "inquiry_line_id"])

    op.create_table(
        "match_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "match_run_id",
            sa.Uuid(),
            sa.ForeignKey("match_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "item_number",
            sa.String(100),
            sa.ForeignKey("catalog_items.item_number", ondelete="SET NULL"),
        ),
        sa.Column("candidate_type", sa.String(50), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("retrieval_evidence", postgresql.JSONB(), nullable=False),
        sa.Column("score_components", postgresql.JSONB(), nullable=False),
        sa.Column("constraint_results", postgresql.JSONB(), nullable=False),
        sa.Column("packaging", postgresql.JSONB(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("match_run_id", "rank", name="uq_match_candidate_rank"),
        sa.CheckConstraint("rank > 0", name="ck_match_candidate_rank"),
    )
    op.create_index("ix_match_candidates_run", "match_candidates", ["match_run_id"])

    op.create_table(
        "match_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "match_run_id",
            sa.Uuid(),
            sa.ForeignKey("match_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("inquiry_line_id", sa.String(500), nullable=False),
        sa.Column("decision_type", sa.String(50), nullable=False),
        sa.Column(
            "candidate_id",
            sa.Uuid(),
            sa.ForeignKey("match_candidates.id", ondelete="SET NULL"),
        ),
        sa.Column("selected_item_number", sa.String(100)),
        sa.Column("offered_quantity", sa.Numeric()),
        sa.Column("override_reason", sa.Text()),
        sa.Column("note", sa.Text()),
        sa.Column("actor", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision_type IN ('accept_suggestion', 'select_alternative', 'manual_match', "
            "'no_match', 'procurement_required')",
            name="ck_match_decision_type",
        ),
        sa.CheckConstraint(
            "offered_quantity IS NULL OR offered_quantity >= 0", name="ck_decision_quantity"
        ),
    )
    op.create_index("ix_match_decisions_run", "match_decisions", ["match_run_id"])

    op.create_table(
        "partner_preferences",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("partner_id", sa.String(300), nullable=False),
        sa.Column("preference_type", sa.String(100), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("source", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="proposed"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'approved', 'retired')", name="ck_partner_preference_status"
        ),
    )
    op.create_index("ix_partner_preferences_partner", "partner_preferences", ["partner_id"])


def downgrade() -> None:
    op.drop_table("partner_preferences")
    op.drop_table("match_decisions")
    op.drop_table("match_candidates")
    op.drop_table("match_runs")
    op.drop_table("historical_offers")
    op.drop_table("product_embeddings")
    op.drop_table("embedding_models")
    op.drop_table("inventory_snapshots")
    op.drop_table("catalog_item_versions")
    op.drop_table("catalog_items")
    op.drop_table("source_snapshots")
    # The vector extension may be shared by other features and is intentionally retained.

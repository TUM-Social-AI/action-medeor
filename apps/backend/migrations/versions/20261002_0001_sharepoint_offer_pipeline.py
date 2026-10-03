"""Durable document processing and independent supplier-offer embeddings."""

from alembic import op

revision = "20261002_0001"
down_revision = "20260930_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sharepoint_sync_items ADD COLUMN created_at TIMESTAMPTZ")
    op.execute("ALTER TABLE sharepoint_sync_items ADD COLUMN domain TEXT")
    op.execute("""
        CREATE TABLE sharepoint_offer_jobs (
            drive_id TEXT NOT NULL, folder_id TEXT NOT NULL, item_id TEXT NOT NULL,
            content_version TEXT NOT NULL, domain TEXT NOT NULL
                CHECK (domain IN ('medicine', 'equipment')),
            item_json JSONB NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','running','completed','failed','unsupported','archived')),
            attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TIMESTAMPTZ,
            lease_token UUID, lease_until TIMESTAMPTZ, error TEXT,
            extraction_version TEXT, result_json JSONB,
            completed_at TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (drive_id, folder_id, item_id)
        )
    """)
    op.execute("CREATE INDEX ix_offer_jobs_status ON sharepoint_offer_jobs(status,next_attempt_at)")
    op.execute("""
        ALTER TABLE historical_offers
            ADD COLUMN source_drive_id TEXT,
            ADD COLUMN source_folder_id TEXT,
            ADD COLUMN source_item_id TEXT,
            ADD COLUMN domain TEXT CHECK (domain IN ('medicine','equipment')),
            ADD COLUMN matching_eligible BOOLEAN NOT NULL DEFAULT TRUE,
            ADD CONSTRAINT fk_offer_processing_job
                FOREIGN KEY (source_drive_id,source_folder_id,source_item_id)
                REFERENCES sharepoint_offer_jobs(drive_id,folder_id,item_id)
    """)
    op.execute("""CREATE INDEX ix_historical_offers_source_file ON historical_offers
        (source_drive_id,source_folder_id,source_item_id)""")
    op.execute("""
        CREATE TABLE offer_embedding_jobs (
            offer_id UUID NOT NULL REFERENCES historical_offers(id) ON DELETE CASCADE,
            model_id VARCHAR(300) NOT NULL REFERENCES embedding_models(id),
            content_hash VARCHAR(64) NOT NULL, content_text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','running','completed','failed')),
            attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TIMESTAMPTZ,
            lease_token UUID, lease_until TIMESTAMPTZ, error TEXT,
            PRIMARY KEY (offer_id,model_id)
        )
    """)
    op.execute("CREATE INDEX ix_offer_embedding_jobs_status ON offer_embedding_jobs(status)")
    op.execute("""
        CREATE TABLE offer_embeddings (
            offer_id UUID NOT NULL REFERENCES historical_offers(id) ON DELETE CASCADE,
            model_id VARCHAR(300) NOT NULL REFERENCES embedding_models(id),
            content_hash VARCHAR(64) NOT NULL, embedding vector NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (offer_id,model_id)
        )
    """)
    op.execute("CREATE INDEX ix_offer_embeddings_hash ON offer_embeddings(model_id,content_hash)")


def downgrade() -> None:
    op.execute("DROP TABLE offer_embeddings")
    op.execute("DROP TABLE offer_embedding_jobs")
    op.execute("ALTER TABLE historical_offers DROP CONSTRAINT fk_offer_processing_job")
    op.execute("DROP INDEX ix_historical_offers_source_file")
    for name in (
        "matching_eligible",
        "domain",
        "source_item_id",
        "source_folder_id",
        "source_drive_id",
    ):
        op.execute(f"ALTER TABLE historical_offers DROP COLUMN {name}")
    op.execute("DROP TABLE sharepoint_offer_jobs")
    op.execute("ALTER TABLE sharepoint_sync_items DROP COLUMN domain, DROP COLUMN created_at")

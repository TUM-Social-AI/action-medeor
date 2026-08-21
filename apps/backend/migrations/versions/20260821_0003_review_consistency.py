"""Make catalogue replay and snapshot selection deterministic.

Revision ID: 20260821_0003
Revises: 20260819_0002
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0003"
down_revision: str | None = "20260819_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Upgrade databases that applied the foundation before its in-branch length fix.
    # SharePoint version identifiers are accepted up to 500 characters by the API.
    op.alter_column(
        "source_snapshots",
        "checksum",
        existing_type=sa.String(128),
        type_=sa.String(500),
        existing_nullable=True,
    )

    # UUIDv4 values do not encode insertion order. Identity columns provide an
    # unambiguous order even when source timestamps are equal.
    op.add_column(
        "catalog_imports",
        sa.Column(
            "import_sequence",
            sa.BigInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_catalog_import_sequence", "catalog_imports", ["import_sequence"]
    )

    op.add_column(
        "catalog_item_versions",
        sa.Column(
            "version_sequence",
            sa.BigInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_catalog_item_version_sequence",
        "catalog_item_versions",
        ["version_sequence"],
    )
    op.create_index(
        "ix_catalog_item_versions_item_sequence",
        "catalog_item_versions",
        ["item_number", "version_sequence"],
    )

    op.add_column(
        "inventory_snapshots",
        sa.Column(
            "inventory_sequence",
            sa.BigInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_inventory_snapshot_sequence",
        "inventory_snapshots",
        ["inventory_sequence"],
    )
    op.create_index(
        "ix_inventory_snapshots_item_sequence",
        "inventory_snapshots",
        ["item_number", "inventory_sequence"],
    )

    # The same file contents may legitimately become current again after an
    # intervening import (A -> B -> A), so checksums are lookup keys, not a
    # globally unique import identity.
    op.drop_constraint("uq_catalog_import_files", "catalog_imports", type_="unique")
    op.create_index(
        "ix_catalog_import_checksums",
        "catalog_imports",
        ["article_checksum", "translation_checksum"],
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_import_checksums", table_name="catalog_imports")
    op.create_unique_constraint(
        "uq_catalog_import_files",
        "catalog_imports",
        ["article_checksum", "translation_checksum"],
    )

    op.drop_index("ix_inventory_snapshots_item_sequence", table_name="inventory_snapshots")
    op.drop_constraint("uq_inventory_snapshot_sequence", "inventory_snapshots", type_="unique")
    op.drop_column("inventory_snapshots", "inventory_sequence")

    op.drop_index("ix_catalog_item_versions_item_sequence", table_name="catalog_item_versions")
    op.drop_constraint("uq_catalog_item_version_sequence", "catalog_item_versions", type_="unique")
    op.drop_column("catalog_item_versions", "version_sequence")

    op.drop_constraint("uq_catalog_import_sequence", "catalog_imports", type_="unique")
    op.drop_column("catalog_imports", "import_sequence")

    op.alter_column(
        "source_snapshots",
        "checksum",
        existing_type=sa.String(500),
        type_=sa.String(128),
        existing_nullable=True,
    )

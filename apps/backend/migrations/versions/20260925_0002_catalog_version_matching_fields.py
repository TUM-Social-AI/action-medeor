"""Keep catalog classification and eligibility on historical item versions.

Revision ID: 20260925_0002
Revises: 20260925_0001
"""

import sqlalchemy as sa
from alembic import op

revision = "20260925_0002"
down_revision = "20260925_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("catalog_item_versions", sa.Column("domain", sa.String(30), nullable=True))
    op.add_column("catalog_item_versions", sa.Column("matching_eligible", sa.Boolean(), nullable=True))
    op.execute(
        """UPDATE catalog_item_versions v
           SET domain = CASE
               WHEN v.attributes ? 'category_code' THEN CASE
                   WHEN LEFT(COALESCE(v.attributes->'category_code'->>'value', ''), 1) = '2'
                        OR v.item_number LIKE '82%' THEN 'medicine'
                   WHEN LEFT(COALESCE(v.attributes->'category_code'->>'value', ''), 1) = '4'
                        OR v.item_number LIKE '84%' THEN 'equipment'
                   ELSE 'unknown' END
               ELSE c.domain END,
               matching_eligible = CASE
                   WHEN v.attributes ? 'category_code' THEN
                       jsonb_array_length(v.descriptions) > 0
                       AND LEFT(COALESCE(v.attributes->'category_code'->>'value', ''), 1)
                           IN ('2', '4')
                       AND NOT COALESCE((v.attributes->'master_item'->>'value')::boolean, FALSE)
                   ELSE c.matching_eligible END
           FROM catalog_items c WHERE c.item_number = v.item_number"""
    )


def downgrade() -> None:
    op.drop_column("catalog_item_versions", "matching_eligible")
    op.drop_column("catalog_item_versions", "domain")

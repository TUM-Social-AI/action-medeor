"""Store supplier offer validity and explicit unit prices.

Revision ID: 20260930_0001
Revises: 20260929_0001
"""

from alembic import op
import sqlalchemy as sa

revision = "20260930_0001"
down_revision = "20260929_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("historical_offers", sa.Column("valid_until", sa.Date()))
    op.add_column("historical_offers", sa.Column("unit_price", sa.Numeric()))
    op.add_column("historical_offers", sa.Column("unit_price_unit", sa.String(100)))


def downgrade() -> None:
    op.drop_column("historical_offers", "unit_price_unit")
    op.drop_column("historical_offers", "unit_price")
    op.drop_column("historical_offers", "valid_until")

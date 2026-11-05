"""Cache German item name translations with their original source text."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_0001"
down_revision = "20261022_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("request_items", sa.Column("german_translation", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("request_items", "german_translation")

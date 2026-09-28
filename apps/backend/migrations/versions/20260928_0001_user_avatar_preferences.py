"""Store the animal avatar chosen by each user.

Revision ID: 20260928_0001
Revises: 20260925_0002
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0001"
down_revision = "20260925_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_avatar_preferences",
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("avatar_id", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_avatar_preferences")

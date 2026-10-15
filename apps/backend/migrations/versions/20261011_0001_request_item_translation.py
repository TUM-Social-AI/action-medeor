"""Store a request item's second-language description in its own column.

Earlier imports folded it into notes as "Translation: <text>" (optionally followed by
" · <original notes>"); those rows are split back out so saved requests show and match the
translation too.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261011_0001"
down_revision = "20261006_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "request_items",
        sa.Column("translation", sa.String(), nullable=False, server_default=""),
    )
    op.execute(
        """
        UPDATE request_items
        SET translation = CASE
                WHEN position(' · ' IN notes) > 0
                THEN substring(notes FROM 14 FOR position(' · ' IN notes) - 14)
                ELSE substring(notes FROM 14)
            END,
            notes = CASE
                WHEN position(' · ' IN notes) > 0
                THEN substring(notes FROM position(' · ' IN notes) + 3)
                ELSE ''
            END
        WHERE notes LIKE 'Translation: %'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE request_items
        SET notes = 'Translation: ' || translation
                    || CASE WHEN notes <> '' THEN ' · ' || notes ELSE '' END
        WHERE translation <> ''
        """
    )
    op.drop_column("request_items", "translation")

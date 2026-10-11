"""Remember a spreadsheet request's worksheets and which one was imported.

Existing requests keep NULL selected_sheet, which every parser treats as "the first worksheet" -
exactly what they were imported from.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261012_0001"
down_revision = "20261006_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "import_requests", sa.Column("sheets", sa.JSON(), nullable=False, server_default="[]")
    )
    op.add_column("import_requests", sa.Column("selected_sheet", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("import_requests", "selected_sheet")
    op.drop_column("import_requests", "sheets")

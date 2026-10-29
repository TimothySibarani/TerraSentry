"""Per-run launch options (scenario, refresh, batch mode).

Revision ID: b4d70c2e9f13
Revises: e3a81f5c7b26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4d70c2e9f13"
down_revision: str | Sequence[str] | None = "e3a81f5c7b26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("options", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("options")

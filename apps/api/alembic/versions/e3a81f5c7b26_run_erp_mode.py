"""Per-run ERP mode: auto, confirm or off.

Revision ID: e3a81f5c7b26
Revises: d915f2b473a8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3a81f5c7b26"
down_revision: str | Sequence[str] | None = "d915f2b473a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("erp_mode", sa.String(length=16), server_default="auto", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("erp_mode")

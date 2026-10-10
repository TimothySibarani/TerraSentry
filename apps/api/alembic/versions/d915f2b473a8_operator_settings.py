"""Singleton operator profile.

Revision ID: d915f2b473a8
Revises: c6e27a901b34
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d915f2b473a8"
down_revision: str | Sequence[str] | None = "c6e27a901b34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operator_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_operator_settings_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operator_settings")),
    )


def downgrade() -> None:
    op.drop_table("operator_settings")

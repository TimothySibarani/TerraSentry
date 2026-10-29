"""Country, legality, provenance and immutable run context.

Revision ID: c6e27a901b34
Revises: 7c1e4b9d2a10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6e27a901b34"
down_revision: str | Sequence[str] | None = "7c1e4b9d2a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
_JSON = sa.JSON()


def upgrade() -> None:
    with op.batch_alter_table("suppliers") as batch:
        batch.add_column(sa.Column("permit_expiry", sa.Date(), nullable=True))
        batch.add_column(sa.Column("declared_holder", sa.String(200), nullable=True))
    with op.batch_alter_table("parcels") as batch:
        batch.add_column(sa.Column("country", sa.String(2), nullable=True))
        batch.add_column(
            sa.Column("provenance", sa.String(24), server_default="legacy_unknown", nullable=False)
        )
    op.execute(
        "UPDATE parcels SET country = 'ID', provenance = 'synthetic' WHERE supplier_id IN "
        "(SELECT supplier_id FROM suppliers WHERE synthetic = true)"
    )
    with op.batch_alter_table("evidence") as batch:
        batch.add_column(sa.Column("provenance", sa.String(24), nullable=True))
    with op.batch_alter_table("verdicts") as batch:
        batch.add_column(sa.Column("assessment_date", sa.Date(), nullable=True))
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("assessment_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("operator_profile", _JSON, nullable=True))


def downgrade() -> None:
    for table, columns in (
        ("runs", ("operator_profile", "assessment_date")),
        ("verdicts", ("assessment_date",)),
        ("evidence", ("provenance",)),
        ("parcels", ("provenance", "country")),
        ("suppliers", ("declared_holder", "permit_expiry")),
    ):
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.drop_column(column)

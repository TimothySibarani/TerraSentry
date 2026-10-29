"""submitted records

Revision ID: 7c1e4b9d2a10
Revises: fa63e54f2542
Create Date: 2026-09-26 16:00:00.000000

Intake (S1): user-submitted plots persist in ``records``; seed design labels
become optional so unlabelled plots fit the existing parcel/verdict rows, and
suppliers carry the provenance of their legality data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c1e4b9d2a10"
down_revision: str | Sequence[str] | None = "fa63e54f2542"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON()


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("suppliers") as batch:
        batch.add_column(
            sa.Column("provenance", sa.String(length=24), server_default="synthetic", nullable=False)
        )
    with op.batch_alter_table("parcels") as batch:
        batch.alter_column("archetype", existing_type=sa.String(length=16), nullable=True)
    with op.batch_alter_table("verdicts") as batch:
        batch.alter_column("expected_archetype", existing_type=sa.String(length=16), nullable=True)
    op.create_table(
        "records",
        sa.Column("record_id", sa.String(length=64), nullable=False),
        sa.Column("supplier_id", sa.String(length=64), nullable=False),
        sa.Column("polygon_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("payload", _JSON, nullable=False),
        sa.Column("geometry", _JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["polygon_id"],
            ["parcels.polygon_id"],
            name=op.f("fk_records_polygon_id_parcels"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.supplier_id"],
            name=op.f("fk_records_supplier_id_suppliers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("record_id", name=op.f("pk_records")),
    )
    op.create_index(op.f("ix_records_supplier_id"), "records", ["supplier_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Unlabelled rows would violate NOT NULL, so drop them first."""
    op.drop_index(op.f("ix_records_supplier_id"), table_name="records")
    op.drop_table("records")
    op.execute("UPDATE verdicts SET expected_archetype = 'unlabelled' WHERE expected_archetype IS NULL")
    op.execute("UPDATE parcels SET archetype = 'unlabelled' WHERE archetype IS NULL")
    with op.batch_alter_table("verdicts") as batch:
        batch.alter_column("expected_archetype", existing_type=sa.String(length=16), nullable=False)
    with op.batch_alter_table("parcels") as batch:
        batch.alter_column("archetype", existing_type=sa.String(length=16), nullable=False)
    with op.batch_alter_table("suppliers") as batch:
        batch.drop_column("provenance")

"""SQLAlchemy models for the API audit store.

The relational shape mirrors the architecture's audit trail: suppliers and
parcels from the synthetic seed, runs and their streamed steps, the evidence
ledger, the deterministic verdict, and the released (or withheld) DDS.

Portability rules:

- JSON columns use ``JSONB`` on PostgreSQL and plain ``JSON`` elsewhere so the
  SQLite unit-test backend can create the same metadata.
- Enums are stored as validated strings (``native_enum=False``) to keep Alembic
  migrations portable and readable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from terrasentry_core.domain.enums import RiskLevel, RunState, Verdict
from terrasentry_core.tools.trace import utc_now

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

JSONType = JSON().with_variant(JSONB(), "postgresql")


def _enum_column(enum_type: type[Any], length: int = 24) -> Enum:
    """A portable, value-backed string enum column."""
    return Enum(
        enum_type,
        native_enum=False,
        length=length,
        values_callable=lambda members: [str(member.value) for member in members],
        validate_strings=True,
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Supplier(Base):
    """Synthetic supplier/entity profile from the seed legality dataset."""

    __tablename__ = "suppliers"

    supplier_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    legal_name: Mapped[str] = mapped_column(String(255))
    trading_name: Mapped[str] = mapped_column(String(255))
    group: Mapped[str] = mapped_column(String(255))
    nib: Mapped[str] = mapped_column(String(32))
    npwp: Mapped[str] = mapped_column(String(32))
    hgu_number: Mapped[str | None] = mapped_column(String(64), default=None)
    pbp_number: Mapped[str | None] = mapped_column(String(64), default=None)
    permit_status: Mapped[str] = mapped_column(String(16), default="active")
    concession_area_ha: Mapped[float] = mapped_column(Float)
    province: Mapped[str] = mapped_column(String(64))
    kabupaten: Mapped[str] = mapped_column(String(64))
    beneficial_owners: Mapped[list[str]] = mapped_column(JSONType, default=list)
    certifications: Mapped[list[str]] = mapped_column(JSONType, default=list)
    sanctions: Mapped[list[str]] = mapped_column(JSONType, default=list)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    disclosure: Mapped[str] = mapped_column(Text, default="")

    parcels: Mapped[list[Parcel]] = relationship(back_populates="supplier")


class Parcel(Base):
    """One plot under assessment: geometry plus the seeded archetype labels."""

    __tablename__ = "parcels"

    polygon_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(
        ForeignKey("suppliers.supplier_id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(255))
    region: Mapped[str] = mapped_column(String(128))
    province: Mapped[str] = mapped_column(String(64))
    area_ha: Mapped[float] = mapped_column(Float)
    centroid_lat: Mapped[float] = mapped_column(Float)
    centroid_lon: Mapped[float] = mapped_column(Float)
    geometry: Mapped[dict[str, Any]] = mapped_column(JSONType)
    archetype: Mapped[str] = mapped_column(String(16))
    scenario: Mapped[str | None] = mapped_column(String(32), default=None)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    supplier: Mapped[Supplier] = relationship(back_populates="parcels")


class Run(Base):
    """A scenario run, a batch parent, or one record inside a batch."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    parent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True, default=None
    )
    record_id: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("suppliers.supplier_id"), default=None)
    polygon_id: Mapped[str | None] = mapped_column(ForeignKey("parcels.polygon_id"), default=None)
    state: Mapped[RunState] = mapped_column(_enum_column(RunState), default=RunState.QUEUED)
    model: Mapped[str] = mapped_column(String(32), default="scripted")
    summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, default=None)
    disclosures: Mapped[list[str]] = mapped_column(JSONType, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    elapsed_seconds: Mapped[float | None] = mapped_column(Float, default=None)
    review_decision: Mapped[str | None] = mapped_column(String(16), default=None)
    review_reviewer: Mapped[str | None] = mapped_column(String(128), default=None)
    review_note: Mapped[str | None] = mapped_column(Text, default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    steps: Mapped[list[RunStep]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="RunStep.seq",
    )
    verdict: Mapped[RunVerdict | None] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )
    dds: Mapped[DdsDocument | None] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )


class RunStep(Base):
    """One streamed step of a run: delegation, tool call, check, write, review."""

    __tablename__ = "run_steps"
    __table_args__ = (UniqueConstraint("run_id", "step_id", name="uq_run_steps_run_id_step_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    step_id: Mapped[str] = mapped_column(String(16))
    seq: Mapped[int]
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    detail: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    run: Mapped[Run] = relationship(back_populates="steps")


class Evidence(Base):
    """One auditable claim backing a score, a DDS field, or a narrative sentence."""

    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("run_id", "evidence_id", name="uq_evidence_run_id_evidence_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    evidence_id: Mapped[str] = mapped_column(String(96))
    schema_version: Mapped[int] = mapped_column(default=1)
    claim: Mapped[str] = mapped_column(String(128))
    value: Mapped[Any] = mapped_column(JSONType)
    unit: Mapped[str | None] = mapped_column(String(32), default=None)
    source: Mapped[str] = mapped_column(String(48))
    artifact: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    disclosure: Mapped[str | None] = mapped_column(Text, default=None)

    run: Mapped[Run] = relationship()


class RunVerdict(Base):
    """The deterministic assessment for one run, released or pending human review."""

    __tablename__ = "verdicts"
    __table_args__ = (UniqueConstraint("run_id", name="uq_verdicts_run_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    record_id: Mapped[str] = mapped_column(String(64))
    supplier_id: Mapped[str] = mapped_column(String(64))
    polygon_id: Mapped[str] = mapped_column(String(64))
    rubric_version: Mapped[str] = mapped_column(String(32))
    score: Mapped[int]
    verdict: Mapped[Verdict] = mapped_column(_enum_column(Verdict))
    risk_level: Mapped[RiskLevel] = mapped_column(_enum_column(RiskLevel))
    fingerprint: Mapped[str] = mapped_column(String(64))
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    citations: Mapped[dict[str, list[str]]] = mapped_column(JSONType, default=dict)
    disclosures: Mapped[list[str]] = mapped_column(JSONType, default=list)
    data_gaps: Mapped[list[str]] = mapped_column(JSONType, default=list)
    expected_archetype: Mapped[str] = mapped_column(String(16))
    expected_signal: Mapped[str | None] = mapped_column(String(16), default=None)
    expected_ambiguity: Mapped[str | None] = mapped_column(String(32), default=None)
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped[Run] = relationship(back_populates="verdict")


class DdsDocument(Base):
    """The built DDS JSON/XML; ``released`` is False while review is pending."""

    __tablename__ = "dds_documents"
    __table_args__ = (UniqueConstraint("run_id", name="uq_dds_documents_run_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    document: Mapped[dict[str, Any]] = mapped_column(JSONType)
    xml: Mapped[str] = mapped_column(Text)
    released: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped[Run] = relationship(back_populates="dds")


__all__ = [
    "Base",
    "DdsDocument",
    "Evidence",
    "JSONType",
    "Parcel",
    "Run",
    "RunStep",
    "RunVerdict",
    "Supplier",
]

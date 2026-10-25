"""SQLAlchemy models for the API audit store.

The relational shape mirrors the architecture's audit trail: suppliers and
parcels from the synthetic seed, runs and their streamed steps, the evidence
ledger, the deterministic verdict, and the released (or withheld) DDS.

JSON uses SQLite text storage; enums are validated strings (``native_enum=False``).
All timestamp columns store UTC and restore timezone information on reads.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator
from terrasentry_core.domain.enums import RiskLevel, RunState, Verdict
from terrasentry_core.tools.trace import utc_now

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UTCDateTime(TypeDecorator[datetime]):
    """SQLite stores naive instants; normalize writes and restore UTC on reads."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None


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
    permit_expiry: Mapped[date | None] = mapped_column(Date, default=None)
    declared_holder: Mapped[str | None] = mapped_column(String(200), default=None)
    permit_status: Mapped[str] = mapped_column(String(16), default="active")
    concession_area_ha: Mapped[float] = mapped_column(Float)
    province: Mapped[str] = mapped_column(String(64))
    kabupaten: Mapped[str] = mapped_column(String(64))
    beneficial_owners: Mapped[list[str]] = mapped_column(JSON, default=list)
    certifications: Mapped[list[str]] = mapped_column(JSON, default=list)
    sanctions: Mapped[list[str]] = mapped_column(JSON, default=list)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    #: synthetic | supplier_declared | document_extracted | sap_import
    provenance: Mapped[str] = mapped_column(String(24), default="synthetic", server_default="synthetic")
    disclosure: Mapped[str] = mapped_column(Text, default="")

    parcels: Mapped[list[Parcel]] = relationship(back_populates="supplier")


class Parcel(Base):
    """One plot under assessment: geometry plus the seeded archetype labels."""

    __tablename__ = "parcels"

    polygon_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(
        ForeignKey("suppliers.supplier_id", ondelete="CASCADE"), index=True
    )
    country: Mapped[str | None] = mapped_column(String(2), default=None)
    provenance: Mapped[str] = mapped_column(
        String(24), default="legacy_unknown", server_default="legacy_unknown"
    )
    label: Mapped[str] = mapped_column(String(255))
    region: Mapped[str] = mapped_column(String(128))
    province: Mapped[str] = mapped_column(String(64))
    area_ha: Mapped[float] = mapped_column(Float)
    centroid_lat: Mapped[float] = mapped_column(Float)
    centroid_lon: Mapped[float] = mapped_column(Float)
    geometry: Mapped[dict[str, Any]] = mapped_column(JSON)
    #: Seed design label; NULL for submitted plots.
    archetype: Mapped[str | None] = mapped_column(String(16), default=None)
    scenario: Mapped[str | None] = mapped_column(String(32), default=None)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    supplier: Mapped[Supplier] = relationship(back_populates="parcels")


class SubmittedRecord(Base):
    """A user-submitted plot record (intake), replayed into the registry at startup.

    ``payload`` is the full ``BatchRecord`` so the agent graph can rebuild the
    exact input it will score; ``geometry`` keeps the geometry as submitted
    (a point stays a point) next to the server-side measurements.
    """

    __tablename__ = "records"

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(
        ForeignKey("suppliers.supplier_id", ondelete="CASCADE"), index=True
    )
    polygon_id: Mapped[str] = mapped_column(ForeignKey("parcels.polygon_id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(24), default="submitted")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    geometry: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class OperatorSetting(Base):
    __tablename__ = "operator_settings"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


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
    assessment_date: Mapped[date | None] = mapped_column(Date, default=None)
    operator_profile: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    model: Mapped[str] = mapped_column(String(32), default="scripted")
    #: ERP side effect: ``auto`` applies on release/decision, ``confirm`` waits for an explicit
    #: confirmation, ``off`` never touches the ERP.
    erp_mode: Mapped[str] = mapped_column(String(16), default="auto", server_default="auto")
    summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, default=None)
    disclosures: Mapped[list[str]] = mapped_column(JSON, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    elapsed_seconds: Mapped[float | None] = mapped_column(Float, default=None)
    review_decision: Mapped[str | None] = mapped_column(String(16), default=None)
    review_reviewer: Mapped[str | None] = mapped_column(String(128), default=None)
    review_note: Mapped[str | None] = mapped_column(Text, default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

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
    at: Mapped[datetime] = mapped_column(UTCDateTime())
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

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
    value: Mapped[Any] = mapped_column(JSON)
    unit: Mapped[str | None] = mapped_column(String(32), default=None)
    source: Mapped[str] = mapped_column(String(48))
    artifact: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    retrieved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    provenance: Mapped[str | None] = mapped_column(String(24), default=None)
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
    assessment_date: Mapped[date | None] = mapped_column(Date, default=None)
    rubric_version: Mapped[str] = mapped_column(String(32))
    score: Mapped[int]
    verdict: Mapped[Verdict] = mapped_column(_enum_column(Verdict))
    risk_level: Mapped[RiskLevel] = mapped_column(_enum_column(RiskLevel))
    fingerprint: Mapped[str] = mapped_column(String(64))
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    citations: Mapped[dict[str, list[str]]] = mapped_column(JSON, default=dict)
    disclosures: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_gaps: Mapped[list[str]] = mapped_column(JSON, default=list)
    expected_archetype: Mapped[str | None] = mapped_column(String(16), default=None)
    expected_signal: Mapped[str | None] = mapped_column(String(16), default=None)
    expected_ambiguity: Mapped[str | None] = mapped_column(String(32), default=None)
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    run: Mapped[Run] = relationship(back_populates="verdict")


class DdsDocument(Base):
    """The built DDS JSON/XML; ``released`` is False while review is pending."""

    __tablename__ = "dds_documents"
    __table_args__ = (UniqueConstraint("run_id", name="uq_dds_documents_run_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    document: Mapped[dict[str, Any]] = mapped_column(JSON)
    xml: Mapped[str] = mapped_column(Text)
    released: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    run: Mapped[Run] = relationship(back_populates="dds")


class SapAction(Base):
    """One ERP-side action triggered by a released verdict or human decision (M7).

    Rows are the audit trail behind the closed loop and the source of truth the
    stub replays at startup (latest action per supplier). ``real`` distinguishes
    a sandbox/live SAP call from the schema-accurate stub, so the demo can state
    exactly which happened.
    """

    __tablename__ = "sap_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    supplier_id: Mapped[str] = mapped_column(String(64), index=True)
    vendor_id: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16), default="stub")
    status: Mapped[str] = mapped_column(String(16))
    purchasing_block: Mapped[bool] = mapped_column(Boolean, default=False)
    real: Mapped[bool] = mapped_column(Boolean, default=False)
    external_reference: Mapped[str | None] = mapped_column(String(255), default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    performed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    run: Mapped[Run] = relationship()


__all__ = [
    "Base",
    "DdsDocument",
    "Evidence",
    "Parcel",
    "Run",
    "RunStep",
    "RunVerdict",
    "SapAction",
    "Supplier",
]

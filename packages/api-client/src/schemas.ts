import { Schema } from "effect";

export class HealthResponse extends Schema.Class<HealthResponse>(
  "terrasentry/api-client/HealthResponse",
)({
  status: Schema.String,
}) {}

export const RunState = Schema.Literals([
  "queued",
  "running",
  "needs_more_data",
  "awaiting_review",
  "complete",
  "failed",
]);
export type RunState = typeof RunState.Type;

export const Verdict = Schema.Literals(["compliant", "high_risk", "ambiguous"]);
export type Verdict = typeof Verdict.Type;

export const RiskLevel = Schema.Literals(["negligible", "non_negligible"]);
export type RiskLevel = typeof RiskLevel.Type;

export const FindingCode = Schema.Literals([
  "deforestation_loss",
  "fire_cluster",
  "legal_permit",
  "area_mismatch",
  "certification",
]);
export type FindingCode = typeof FindingCode.Type;

export const FindingLevel = Schema.Literals(["clear", "borderline", "flag"]);
export type FindingLevel = typeof FindingLevel.Type;

export const EvidenceSource = Schema.Literals([
  "global_forest_watch",
  "nasa_firms",
  "legality_dataset",
  "concession_dataset",
  "consignment_dataset",
  "operator_dataset",
  "deterministic_rubric",
]);
export type EvidenceSource = typeof EvidenceSource.Type;

export const TraceKind = Schema.Literals([
  "run",
  "agent",
  "tool",
  "verifier",
  "writer",
  "review",
  "state",
]);
export type TraceKind = typeof TraceKind.Type;

export const ModelMode = Schema.Literals(["scripted", "bedrock"]);
export type ModelMode = typeof ModelMode.Type;

export class Finding extends Schema.Class<Finding>(
  "terrasentry/api-client/Finding",
)({
  code: FindingCode,
  level: FindingLevel,
  points: Schema.Int,
  detail: Schema.String,
  metrics: Schema.Record(
    Schema.String,
    Schema.Union([Schema.Number, Schema.String]),
  ),
  evidence_ids: Schema.Array(Schema.String),
  mitigating: Schema.Boolean,
}) {}

export class Assessment extends Schema.Class<Assessment>(
  "terrasentry/api-client/Assessment",
)({
  record_id: Schema.NullOr(Schema.String),
  supplier_id: Schema.String,
  polygon_id: Schema.String,
  rubric_version: Schema.String,
  score: Schema.Int,
  verdict: Verdict,
  risk_level: RiskLevel,
  findings: Schema.Array(Finding),
  citations: Schema.Record(Schema.String, Schema.Array(Schema.String)),
  disclosures: Schema.Array(Schema.String),
  data_gaps: Schema.Array(Schema.String),
}) {}

export class VerificationChallenge extends Schema.Class<VerificationChallenge>(
  "terrasentry/api-client/VerificationChallenge",
)({
  kind: Schema.String,
  severity: Schema.Literals(["info", "warning", "error"]),
  detail: Schema.String,
  source: Schema.String,
  evidence_ids: Schema.Array(Schema.String),
  expected: Schema.NullOr(Schema.String),
  observed: Schema.NullOr(Schema.String),
}) {}

export class VerificationReport extends Schema.Class<VerificationReport>(
  "terrasentry/api-client/VerificationReport",
)({
  accepted: Schema.Boolean,
  checked_claims: Schema.Array(Schema.String),
  challenges: Schema.Array(VerificationChallenge),
  notes: Schema.Array(Schema.String),
  llm_reviewed: Schema.Boolean,
  model_id: Schema.NullOr(Schema.String),
}) {}

export class TraceStep extends Schema.Class<TraceStep>(
  "terrasentry/api-client/TraceStep",
)({
  step_id: Schema.String,
  kind: TraceKind,
  name: Schema.String,
  detail: Schema.String,
  at: Schema.DateTimeUtcFromString,
  payload: Schema.Record(Schema.String, Schema.Unknown),
}) {}

export class ReviewOut extends Schema.Class<ReviewOut>(
  "terrasentry/api-client/ReviewOut",
)({
  decision: Schema.Literals(["approve", "override"]),
  reviewer: Schema.String,
  note: Schema.String,
  reviewed_at: Schema.NullOr(Schema.DateTimeUtcFromString),
}) {}

export class DdsMeta extends Schema.Class<DdsMeta>(
  "terrasentry/api-client/DdsMeta",
)({
  released: Schema.Boolean,
  schema_version: Schema.String,
  created_at: Schema.DateTimeUtcFromString,
}) {}

const runSummaryFields = {
  run_id: Schema.String,
  kind: Schema.String,
  state: RunState,
  record_id: Schema.NullOr(Schema.String),
  supplier_id: Schema.NullOr(Schema.String),
  polygon_id: Schema.NullOr(Schema.String),
  parent_run_id: Schema.NullOr(Schema.String),
  model: Schema.String,
  summary: Schema.String,
  error: Schema.NullOr(Schema.String),
  verdict: Schema.NullOr(Verdict),
  score: Schema.NullOr(Schema.Int),
  expected_archetype: Schema.NullOr(Schema.String),
  step_count: Schema.Int,
  started_at: Schema.NullOr(Schema.DateTimeUtcFromString),
  finished_at: Schema.NullOr(Schema.DateTimeUtcFromString),
  elapsed_seconds: Schema.NullOr(Schema.Number),
  created_at: Schema.DateTimeUtcFromString,
  metrics: Schema.Record(Schema.String, Schema.Unknown),
} as const;

export class RunSummary extends Schema.Class<RunSummary>(
  "terrasentry/api-client/RunSummary",
)(runSummaryFields) {}

export class VerdictOut extends Schema.Class<VerdictOut>(
  "terrasentry/api-client/VerdictOut",
)({
  record_id: Schema.String,
  supplier_id: Schema.String,
  polygon_id: Schema.String,
  run_state: RunState,
  expected_archetype: Schema.String,
  expected_signal: Schema.NullOr(Schema.String),
  expected_ambiguity: Schema.NullOr(Schema.String),
  fingerprint: Schema.String,
  pending: Schema.Boolean,
  assessment: Assessment,
}) {}

export class RunDetail extends Schema.Class<RunDetail>(
  "terrasentry/api-client/RunDetail",
)({
  ...runSummaryFields,
  disclosures: Schema.Array(Schema.String),
  verification: Schema.NullOr(VerificationReport),
  assessment: Schema.NullOr(VerdictOut),
  pending_assessment: Schema.NullOr(VerdictOut),
  review: Schema.NullOr(ReviewOut),
  steps: Schema.Array(TraceStep),
  dds: Schema.NullOr(DdsMeta),
}) {}

export class BatchSummary extends Schema.Class<BatchSummary>(
  "terrasentry/api-client/BatchSummary",
)({
  run_id: Schema.String,
  state: RunState,
  record_count: Schema.Int,
  states: Schema.Record(Schema.String, Schema.Int),
  verdict_breakdown: Schema.Record(Schema.String, Schema.Int),
  expected_breakdown: Schema.Record(Schema.String, Schema.Int),
  wall_clock_seconds: Schema.NullOr(Schema.Number),
  average_seconds_per_record: Schema.NullOr(Schema.Number),
  started_at: Schema.NullOr(Schema.DateTimeUtcFromString),
  finished_at: Schema.NullOr(Schema.DateTimeUtcFromString),
  metrics: Schema.Record(Schema.String, Schema.Unknown),
}) {}

export class ParcelOut extends Schema.Class<ParcelOut>(
  "terrasentry/api-client/ParcelOut",
)({
  polygon_id: Schema.String,
  supplier_id: Schema.String,
  label: Schema.String,
  region: Schema.String,
  province: Schema.String,
  area_ha: Schema.Number,
  centroid_lat: Schema.Number,
  centroid_lon: Schema.Number,
  geometry: Schema.Record(Schema.String, Schema.Unknown),
  archetype: Schema.String,
  scenario: Schema.NullOr(Schema.String),
  is_demo: Schema.Boolean,
}) {}

const supplierFields = {
  supplier_id: Schema.String,
  legal_name: Schema.String,
  trading_name: Schema.String,
  group: Schema.String,
  nib: Schema.String,
  npwp: Schema.String,
  hgu_number: Schema.NullOr(Schema.String),
  pbp_number: Schema.NullOr(Schema.String),
  permit_status: Schema.String,
  concession_area_ha: Schema.Number,
  province: Schema.String,
  kabupaten: Schema.String,
  beneficial_owners: Schema.Array(Schema.String),
  certifications: Schema.Array(Schema.String),
  sanctions: Schema.Array(Schema.String),
  synthetic: Schema.Boolean,
  disclosure: Schema.String,
} as const;

export class SupplierOut extends Schema.Class<SupplierOut>(
  "terrasentry/api-client/SupplierOut",
)(supplierFields) {}

export class SupplierDetail extends Schema.Class<SupplierDetail>(
  "terrasentry/api-client/SupplierDetail",
)({
  ...supplierFields,
  parcels: Schema.Array(ParcelOut),
}) {}

export class EvidenceEntry extends Schema.Class<EvidenceEntry>(
  "terrasentry/api-client/EvidenceEntry",
)({
  schema_version: Schema.Int,
  evidence_id: Schema.String,
  claim: Schema.String,
  value: Schema.Unknown,
  unit: Schema.NullOr(Schema.String),
  source: EvidenceSource,
  artifact: Schema.Record(Schema.String, Schema.Unknown),
  retrieved_at: Schema.NullOr(Schema.DateTimeUtcFromString),
  cached: Schema.Boolean,
  synthetic: Schema.Boolean,
  disclosure: Schema.NullOr(Schema.String),
}) {}

export class SapVendorOut extends Schema.Class<SapVendorOut>(
  "terrasentry/api-client/SapVendorOut",
)({
  vendor_id: Schema.String,
  status: Schema.String,
  purchasing_block: Schema.Boolean,
}) {}

export const RunCreateRequest = Schema.Struct({
  record_id: Schema.optional(Schema.String),
  scenario: Schema.optional(Schema.String),
  model: Schema.optional(ModelMode),
  refresh: Schema.optional(Schema.Boolean),
});
export type RunCreateRequest = typeof RunCreateRequest.Type;

export const DecisionRequest = Schema.Struct({
  decision: Schema.Literals(["approve", "override"]),
  reviewer: Schema.optional(Schema.String),
  note: Schema.optional(Schema.String),
});
export type DecisionRequest = typeof DecisionRequest.Type;

export const BatchCreateRequest = Schema.Struct({
  size: Schema.optional(Schema.Int),
  refresh: Schema.optional(Schema.Boolean),
});
export type BatchCreateRequest = typeof BatchCreateRequest.Type;

export const SapStatusRequest = Schema.Struct({ status: Schema.String });
export type SapStatusRequest = typeof SapStatusRequest.Type;

export const SapBlockRequest = Schema.Struct({ blocked: Schema.Boolean });
export type SapBlockRequest = typeof SapBlockRequest.Type;

const SnapshotData = Schema.Struct({
  run_id: Schema.String,
  kind: Schema.String,
  state: RunState,
  record_id: Schema.NullOr(Schema.String),
  parent_run_id: Schema.NullOr(Schema.String),
  verdict: Schema.NullOr(Verdict),
  score: Schema.NullOr(Schema.Int),
  dds_released: Schema.Boolean,
});

const StateData = Schema.Struct({
  run_id: Schema.String,
  state: RunState,
});

const ProgressData = Schema.Struct({
  run_id: Schema.String,
  total: Schema.Int,
  completed: Schema.Int,
  failed: Schema.Int,
  awaiting_review: Schema.Int,
  verdict_breakdown: Schema.Record(Schema.String, Schema.Int),
});

export const RunEvent = Schema.Union([
  Schema.Struct({ event: Schema.Literal("snapshot"), data: SnapshotData }),
  Schema.Struct({ event: Schema.Literal("step"), data: TraceStep }),
  Schema.Struct({ event: Schema.Literal("state"), data: StateData }),
  Schema.Struct({ event: Schema.Literal("done"), data: StateData }),
  Schema.Struct({ event: Schema.Literal("progress"), data: ProgressData }),
]);
export type RunEvent = typeof RunEvent.Type;

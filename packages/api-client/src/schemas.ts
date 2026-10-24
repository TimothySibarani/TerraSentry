import { Option, Schema } from "effect";

/**
 * Plain `Schema.Struct`s, not `Schema.Class`es: decoded payloads cross the
 * TanStack Start SSR boundary, and Seroval only serializes plain objects.
 */

export const HealthResponse = Schema.Struct({
  status: Schema.String,
  offline: Schema.Boolean,
  fixtures_loaded: Schema.Int,
  sap_mode: Schema.String,
  sap_real: Schema.Boolean,
  aicore_configured: Schema.Boolean,
  adverse_media_mode: Schema.String,
  default_model: Schema.String,
  gfw_configured: Schema.Boolean,
  firms_configured: Schema.Boolean,
  auth_enabled: Schema.Boolean,
});
export type HealthResponse = typeof HealthResponse.Type;

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
  "protected_area",
  "moratorium",
  "peatland",
  "concession_conflict",
  "forest_baseline",
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

export const Provenance = Schema.Literals([
  "synthetic",
  "supplier_declared",
  "document_extracted",
  "sap_import",
  "real_source",
  "operator_configured",
  "derived",
  "legacy_unknown",
]);
export type Provenance = typeof Provenance.Type;

export const OperatorUpdate = Schema.Struct({
  legal_name: Schema.String,
  identifier_type: Schema.Literals(["eori"]),
  identifier_value: Schema.String,
  address_line: Schema.String,
  postal_code: Schema.String,
  city: Schema.String,
  country: Schema.String,
  email: Schema.String,
  phone: Schema.String,
  activity_type: Schema.Literals(["IMPORT", "EXPORT", "DOMESTIC"]),
  country_of_activity: Schema.String,
  border_cross_country: Schema.String,
});
export type OperatorUpdate = typeof OperatorUpdate.Type;
export const OperatorRecord = Schema.Struct({
  ...OperatorUpdate.fields,
  operator_id: Schema.String,
  synthetic: Schema.Boolean,
  provenance: Provenance,
  disclosure: Schema.String,
});
export type OperatorRecord = typeof OperatorRecord.Type;
export const OperatorSettingOut = Schema.Struct({
  profile: OperatorRecord,
  configured: Schema.Boolean,
  updated_at: Schema.NullOr(Schema.DateTimeUtcFromString),
});
export type OperatorSettingOut = typeof OperatorSettingOut.Type;

export const TraceKind = Schema.Literals([
  "run",
  "agent",
  "retask",
  "report",
  "tool",
  "verifier",
  "writer",
  "review",
  "state",
  "sap",
]);
export type TraceKind = typeof TraceKind.Type;

export const ModelMode = Schema.Literals(["scripted", "sap"]);
export type ModelMode = typeof ModelMode.Type;

export const Finding = Schema.Struct({
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
});
export type Finding = typeof Finding.Type;

export const Assessment = Schema.Struct({
  assessment_date: Schema.optional(Schema.NullOr(Schema.String)),
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
});
export type Assessment = typeof Assessment.Type;

export const VerificationChallenge = Schema.Struct({
  kind: Schema.String,
  severity: Schema.Literals(["info", "warning", "error"]),
  detail: Schema.String,
  source: Schema.String,
  evidence_ids: Schema.Array(Schema.String),
  expected: Schema.NullOr(Schema.String),
  observed: Schema.NullOr(Schema.String),
});
export type VerificationChallenge = typeof VerificationChallenge.Type;

export const VerificationReport = Schema.Struct({
  accepted: Schema.Boolean,
  checked_claims: Schema.Array(Schema.String),
  challenges: Schema.Array(VerificationChallenge),
  notes: Schema.Array(Schema.String),
  llm_reviewed: Schema.Boolean,
  model_id: Schema.NullOr(Schema.String),
});
export type VerificationReport = typeof VerificationReport.Type;

export const TraceStep = Schema.Struct({
  step_id: Schema.String,
  kind: TraceKind,
  name: Schema.String,
  detail: Schema.String,
  at: Schema.DateTimeUtcFromString,
  payload: Schema.Record(Schema.String, Schema.Unknown),
});
export type TraceStep = typeof TraceStep.Type;

/** Adverse-media context carried in a `search_adverse_media` trace step. Never a scoring input. */
export const MediaCitation = Schema.Struct({
  url: Schema.String,
  title: Schema.String,
  published: Schema.NullOr(Schema.String),
});
export type MediaCitation = typeof MediaCitation.Type;

export const MediaFinding = Schema.Struct({
  claim: Schema.String,
  citations: Schema.Array(MediaCitation),
});
export type MediaFinding = typeof MediaFinding.Type;

export const AdverseMediaReport = Schema.Struct({
  subject: Schema.String,
  country: Schema.NullOr(Schema.String),
  status: Schema.Literals(["success", "unavailable"]),
  summary: Schema.String,
  findings: Schema.Array(MediaFinding),
  model: Schema.String,
  synthetic: Schema.Boolean,
  disclosure: Schema.NullOr(Schema.String),
  cached: Schema.Boolean,
  error: Schema.NullOr(Schema.String),
});
export type AdverseMediaReport = typeof AdverseMediaReport.Type;

const AdverseMediaStepPayload = Schema.Struct({ report: AdverseMediaReport });

/** The run's adverse-media report, or `null` when the layer was off or the step is malformed. */
export const adverseMediaFromSteps = (
  steps: ReadonlyArray<TraceStep>,
): AdverseMediaReport | null => {
  const step = steps.find(
    (candidate) =>
      candidate.kind === "tool" && candidate.name === "search_adverse_media",
  );
  if (step === undefined) return null;
  return Option.getOrNull(
    Option.map(
      Schema.decodeUnknownOption(AdverseMediaStepPayload)(step.payload),
      (payload) => payload.report,
    ),
  );
};

export const ReviewOut = Schema.Struct({
  decision: Schema.Literals(["approve", "override"]),
  reviewer: Schema.String,
  note: Schema.String,
  reviewed_at: Schema.NullOr(Schema.DateTimeUtcFromString),
});
export type ReviewOut = typeof ReviewOut.Type;

export const DdsMeta = Schema.Struct({
  released: Schema.Boolean,
  schema_version: Schema.String,
  created_at: Schema.DateTimeUtcFromString,
});
export type DdsMeta = typeof DdsMeta.Type;

export const SapActionOut = Schema.Struct({
  run_id: Schema.String,
  supplier_id: Schema.String,
  vendor_id: Schema.String,
  mode: Schema.String,
  status: Schema.String,
  purchasing_block: Schema.Boolean,
  real: Schema.Boolean,
  external_reference: Schema.NullOr(Schema.String),
  error: Schema.NullOr(Schema.String),
  performed_at: Schema.DateTimeUtcFromString,
});
export type SapActionOut = typeof SapActionOut.Type;

export const SupplierSapOut = Schema.Struct({
  vendor_id: Schema.String,
  status: Schema.String,
  purchasing_block: Schema.Boolean,
  mode: Schema.String,
  real: Schema.Boolean,
  disclosure: Schema.String,
  last_action: Schema.NullOr(SapActionOut),
});
export type SupplierSapOut = typeof SupplierSapOut.Type;

export const ErpMode = Schema.Literals(["off", "confirm", "auto"]);
export type ErpMode = typeof ErpMode.Type;

const runSummaryFields = {
  run_id: Schema.String,
  kind: Schema.String,
  state: RunState,
  record_id: Schema.NullOr(Schema.String),
  supplier_id: Schema.NullOr(Schema.String),
  polygon_id: Schema.NullOr(Schema.String),
  parent_run_id: Schema.NullOr(Schema.String),
  model: Schema.String,
  erp_mode: ErpMode,
  assessment_date: Schema.optional(Schema.NullOr(Schema.String)),
  operator_profile: Schema.optional(Schema.NullOr(OperatorRecord)),
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

export const RunSummary = Schema.Struct(runSummaryFields);
export type RunSummary = typeof RunSummary.Type;

export const VerdictOut = Schema.Struct({
  record_id: Schema.String,
  supplier_id: Schema.String,
  polygon_id: Schema.String,
  run_state: RunState,
  expected_archetype: Schema.NullOr(Schema.String),
  expected_signal: Schema.NullOr(Schema.String),
  expected_ambiguity: Schema.NullOr(Schema.String),
  fingerprint: Schema.String,
  pending: Schema.Boolean,
  assessment: Assessment,
});
export type VerdictOut = typeof VerdictOut.Type;

export const RunDetail = Schema.Struct({
  ...runSummaryFields,
  disclosures: Schema.Array(Schema.String),
  verification: Schema.NullOr(VerificationReport),
  assessment: Schema.NullOr(VerdictOut),
  pending_assessment: Schema.NullOr(VerdictOut),
  review: Schema.NullOr(ReviewOut),
  sap_action: Schema.NullOr(SapActionOut),
  // In `confirm` mode: the vendor status waiting for an explicit confirmation.
  erp_pending: Schema.optional(
    Schema.NullOr(Schema.Literals(["approved", "blocked"])),
  ),
  steps: Schema.Array(TraceStep),
  dds: Schema.NullOr(DdsMeta),
});
export type RunDetail = typeof RunDetail.Type;

export const BatchMode = Schema.Literals(["screening", "agent"]);
export type BatchMode = typeof BatchMode.Type;

export const BatchSummary = Schema.Struct({
  run_id: Schema.String,
  state: RunState,
  mode: BatchMode,
  model: Schema.NullOr(Schema.String),
  record_count: Schema.Int,
  unlabelled_count: Schema.Int,
  states: Schema.Record(Schema.String, Schema.Int),
  verdict_breakdown: Schema.Record(Schema.String, Schema.Int),
  expected_breakdown: Schema.Record(Schema.String, Schema.Int),
  wall_clock_seconds: Schema.NullOr(Schema.Number),
  average_seconds_per_record: Schema.NullOr(Schema.Number),
  median_seconds_per_record: Schema.NullOr(Schema.Number),
  p95_seconds_per_record: Schema.NullOr(Schema.Number),
  throughput_records_per_second: Schema.NullOr(Schema.Number),
  total_record_seconds: Schema.NullOr(Schema.Number),
  cache_stats: Schema.NullOr(Schema.Record(Schema.String, Schema.Int)),
  confusion: Schema.Record(
    Schema.String,
    Schema.Record(Schema.String, Schema.Int),
  ),
  batch_concurrency: Schema.NullOr(Schema.Int),
  sap_actions: Schema.Record(Schema.String, Schema.Int),
  started_at: Schema.NullOr(Schema.DateTimeUtcFromString),
  finished_at: Schema.NullOr(Schema.DateTimeUtcFromString),
  metrics: Schema.Record(Schema.String, Schema.Unknown),
});
export type BatchSummary = typeof BatchSummary.Type;

export const ParcelOut = Schema.Struct({
  country: Schema.optional(Schema.NullOr(Schema.String)),
  provenance: Schema.optional(Provenance),
  polygon_id: Schema.String,
  supplier_id: Schema.String,
  label: Schema.String,
  region: Schema.String,
  province: Schema.String,
  area_ha: Schema.Number,
  centroid_lat: Schema.Number,
  centroid_lon: Schema.Number,
  geometry: Schema.Record(Schema.String, Schema.Unknown),
  archetype: Schema.NullOr(Schema.String),
  scenario: Schema.NullOr(Schema.String),
  is_demo: Schema.Boolean,
});
export type ParcelOut = typeof ParcelOut.Type;

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
  permit_expiry: Schema.optional(Schema.NullOr(Schema.String)),
  declared_holder: Schema.optional(Schema.NullOr(Schema.String)),
  concession_area_ha: Schema.Number,
  province: Schema.String,
  kabupaten: Schema.String,
  beneficial_owners: Schema.Array(Schema.String),
  certifications: Schema.Array(Schema.String),
  sanctions: Schema.Array(Schema.String),
  synthetic: Schema.Boolean,
  provenance: Schema.String,
  disclosure: Schema.String,
} as const;

export const SupplierOut = Schema.Struct(supplierFields);
export type SupplierOut = typeof SupplierOut.Type;

export const SupplierDetail = Schema.Struct({
  ...supplierFields,
  parcels: Schema.Array(ParcelOut),
  sap: Schema.NullOr(SupplierSapOut),
});
export type SupplierDetail = typeof SupplierDetail.Type;

export const EvidenceEntry = Schema.Struct({
  provenance: Schema.optional(Provenance),
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
});
export type EvidenceEntry = typeof EvidenceEntry.Type;

export const SapVendorOut = Schema.Struct({
  vendor_id: Schema.String,
  status: Schema.String,
  purchasing_block: Schema.Boolean,
});
export type SapVendorOut = typeof SapVendorOut.Type;

export const RunCreateRequest = Schema.Struct({
  record_id: Schema.optional(Schema.String),
  scenario: Schema.optional(Schema.String),
  model: Schema.optional(ModelMode),
  refresh: Schema.optional(Schema.Boolean),
  erp_mode: Schema.optional(ErpMode),
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
  record_ids: Schema.optional(Schema.Array(Schema.String)),
  mode: Schema.optional(BatchMode),
  model: Schema.optional(ModelMode),
  erp_mode: Schema.optional(ErpMode),
});
export type BatchCreateRequest = typeof BatchCreateRequest.Type;

export const SapStatusRequest = Schema.Struct({ status: Schema.String });
export type SapStatusRequest = typeof SapStatusRequest.Type;

export const SapBlockRequest = Schema.Struct({ blocked: Schema.Boolean });
export type SapBlockRequest = typeof SapBlockRequest.Type;

const ProgressData = Schema.Struct({
  run_id: Schema.String,
  total: Schema.Int,
  completed: Schema.Int,
  failed: Schema.Int,
  awaiting_review: Schema.Int,
  verdict_breakdown: Schema.Record(Schema.String, Schema.Int),
  elapsed_seconds: Schema.optionalKey(Schema.NullOr(Schema.Number)),
});

const SnapshotData = Schema.Struct({
  run_id: Schema.String,
  kind: Schema.String,
  state: RunState,
  record_id: Schema.NullOr(Schema.String),
  parent_run_id: Schema.NullOr(Schema.String),
  verdict: Schema.NullOr(Verdict),
  score: Schema.NullOr(Schema.Int),
  dds_released: Schema.Boolean,
  progress: Schema.optionalKey(ProgressData),
});

const StateData = Schema.Struct({
  run_id: Schema.String,
  state: RunState,
});

export const RunEvent = Schema.Union([
  Schema.Struct({ event: Schema.Literal("snapshot"), data: SnapshotData }),
  Schema.Struct({ event: Schema.Literal("step"), data: TraceStep }),
  Schema.Struct({ event: Schema.Literal("state"), data: StateData }),
  Schema.Struct({ event: Schema.Literal("done"), data: StateData }),
  Schema.Struct({ event: Schema.Literal("progress"), data: ProgressData }),
]);
export type RunEvent = typeof RunEvent.Type;

// -- intake (submitted plots) --------------------------------------------------

export const Commodity = Schema.Literals([
  "oil_palm",
  "wood",
  "rubber",
  "cocoa",
  "coffee",
]);
export type Commodity = typeof Commodity.Type;

export const PermitType = Schema.Literals(["hgu", "pbph", "none"]);
export type PermitType = typeof PermitType.Type;

export const PermitStatus = Schema.Literals([
  "active",
  "expired",
  "suspended",
  "none",
]);
export type PermitStatus = typeof PermitStatus.Type;

const GeoJsonObject = Schema.Record(Schema.String, Schema.Unknown);

export const RecordSubmission = Schema.Struct({
  plot: Schema.Struct({
    geometry: GeoJsonObject,
    country: Schema.String,
    label: Schema.String,
    province: Schema.optional(Schema.String),
    kabupaten: Schema.optional(Schema.String),
    declared_area_ha: Schema.optional(Schema.NullOr(Schema.Number)),
  }),
  supplier: Schema.Struct({
    legal_name: Schema.String,
    trading_name: Schema.optional(Schema.String),
    group: Schema.optional(Schema.String),
    nib: Schema.optional(Schema.String),
    npwp: Schema.optional(Schema.String),
    beneficial_owners: Schema.optional(Schema.Array(Schema.String)),
    certifications: Schema.optional(Schema.Array(Schema.String)),
  }),
  legality: Schema.optional(
    Schema.Struct({
      permit_expiry: Schema.optional(Schema.NullOr(Schema.String)),
      declared_holder: Schema.optional(Schema.String),
      permit_type: Schema.optional(PermitType),
      permit_number: Schema.optional(Schema.String),
      permit_status: Schema.optional(PermitStatus),
      concession_area_ha: Schema.optional(Schema.NullOr(Schema.Number)),
      sanctions: Schema.optional(Schema.Array(Schema.String)),
    }),
  ),
  consignment: Schema.Struct({
    commodity: Commodity,
    description: Schema.String,
    hs_heading: Schema.optional(Schema.String),
    species_scientific: Schema.optional(Schema.String),
    species_common: Schema.optional(Schema.String),
    net_weight_kg: Schema.Number,
    harvest_year: Schema.Int,
  }),
});
export type RecordSubmission = typeof RecordSubmission.Type;

export const GeometryCheckRequest = Schema.Struct({
  geometry: GeoJsonObject,
  declared_area_ha: Schema.optional(Schema.NullOr(Schema.Number)),
});
export type GeometryCheckRequest = typeof GeometryCheckRequest.Type;

export const GeometryReport = Schema.Struct({
  geometry: GeoJsonObject,
  query_geometry: GeoJsonObject,
  geometry_type: Schema.String,
  area_ha: Schema.Number,
  centroid_lat: Schema.Number,
  centroid_lon: Schema.Number,
  vertex_count: Schema.Int,
});
export type GeometryReport = typeof GeometryReport.Type;

export const LatestRunOut = Schema.Struct({
  run_id: Schema.String,
  state: RunState,
  verdict: Schema.NullOr(Verdict),
  score: Schema.NullOr(Schema.Int),
  model: Schema.String,
  created_at: Schema.DateTimeUtcFromString,
});
export type LatestRunOut = typeof LatestRunOut.Type;

export const RecordOut = Schema.Struct({
  country: Schema.optional(Schema.NullOr(Schema.String)),
  geometry_provenance: Schema.optional(Provenance),
  record_id: Schema.String,
  supplier_id: Schema.String,
  polygon_id: Schema.String,
  source: Schema.String,
  created_at: Schema.DateTimeUtcFromString,
  label: Schema.String,
  region: Schema.String,
  area_ha: Schema.Number,
  centroid_lat: Schema.Number,
  centroid_lon: Schema.Number,
  geometry_type: Schema.String,
  geometry: GeoJsonObject,
  legal_name: Schema.String,
  commodity: Schema.String,
  description: Schema.String,
  hs_heading: Schema.String,
  net_weight_kg: Schema.Number,
  permit_status: Schema.String,
  permit_expiry: Schema.optional(Schema.NullOr(Schema.String)),
  declared_holder: Schema.optional(Schema.NullOr(Schema.String)),
  hgu_number: Schema.NullOr(Schema.String),
  pbp_number: Schema.NullOr(Schema.String),
  provenance: Schema.String,
  disclosure: Schema.String,
  latest_run: Schema.NullOr(LatestRunOut),
});
export type RecordOut = typeof RecordOut.Type;

export const ImportResult = Schema.Struct({
  created: Schema.Array(RecordOut),
  errors: Schema.Array(
    Schema.Struct({
      row: Schema.Int,
      field: Schema.String,
      message: Schema.String,
    }),
  ),
  total_rows: Schema.Int,
});
export type ImportResult = typeof ImportResult.Type;

/** FastAPI's 422 body; intake errors reuse the same shape. */
export const ValidationErrorBody = Schema.Struct({
  detail: Schema.Array(
    Schema.Struct({
      loc: Schema.Array(Schema.Union([Schema.String, Schema.Number])),
      msg: Schema.String,
    }),
  ),
});
export type ValidationErrorBody = typeof ValidationErrorBody.Type;

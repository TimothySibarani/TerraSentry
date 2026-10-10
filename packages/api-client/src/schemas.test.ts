import { assert, describe, it } from "@effect/vitest";
import { DateTime, Effect, Schema, Stream } from "effect";

import { decodeRunEventStream } from "./client";
import {
  adverseMediaFromSteps,
  BatchSummary,
  HealthResponse,
  RunDetail,
  RunEvent,
  RunSummary,
  TraceStep,
} from "./schemas";

describe("HealthResponse", () => {
  it.effect("decodes the API health payload", () =>
    Effect.gen(function* () {
      const health = yield* Schema.decodeUnknownEffect(HealthResponse)({
        status: "ok",
        offline: false,
        fixtures_loaded: 0,
        sap_mode: "stub",
        sap_real: false,
        bedrock_configured: false,
        aicore_configured: true,
        adverse_media_mode: "stub",
        default_model: "scripted",
        gfw_configured: true,
        firms_configured: true,
        auth_enabled: false,
      });
      assert.strictEqual(health.status, "ok");
      assert.strictEqual(health.offline, false);
      assert.strictEqual(health.fixtures_loaded, 0);
      assert.strictEqual(health.sap_mode, "stub");
    }),
  );

  it.effect("rejects a payload without a status", () =>
    Effect.gen(function* () {
      const result = yield* Effect.exit(
        Schema.decodeUnknownEffect(HealthResponse)({}),
      );
      assert.strictEqual(result._tag, "Failure");
    }),
  );
});

const runSummary = {
  run_id: "run-1",
  kind: "scenario",
  state: "complete",
  record_id: "REC-001",
  supplier_id: "SUP-001",
  polygon_id: "POLY-001",
  parent_run_id: null,
  model: "scripted",
  summary: "compliant score 0",
  error: null,
  verdict: "compliant",
  score: 0,
  expected_archetype: "compliant",
  step_count: 1,
  started_at: "2026-09-11T10:00:00Z",
  finished_at: "2026-09-11T10:00:01Z",
  elapsed_seconds: 1.25,
  created_at: "2026-09-11T10:00:00Z",
  metrics: {},
};

const step = {
  step_id: "STEP-001",
  kind: "state",
  name: "queued",
  detail: "REC-001",
  at: "2026-09-11T10:00:00Z",
  payload: {},
};

const sapStep = {
  step_id: "STEP-002",
  kind: "sap",
  name: "sap_action",
  detail: "SUP-001: approved via stub (stub)",
  at: "2026-09-11T10:00:01Z",
  payload: {
    vendor_id: "SUP-001",
    status: "approved",
    purchasing_block: false,
    mode: "stub",
    real: false,
    error: null,
  },
};

const sapAction = {
  run_id: "run-1",
  supplier_id: "SUP-001",
  vendor_id: "SUP-001",
  mode: "stub",
  status: "approved",
  purchasing_block: false,
  real: false,
  external_reference: null,
  error: null,
  performed_at: "2026-09-11T10:00:01Z",
};

const assessment = {
  record_id: "REC-001",
  supplier_id: "SUP-001",
  polygon_id: "POLY-001",
  rubric_version: "1.0.0",
  score: 0,
  verdict: "compliant",
  risk_level: "negligible",
  findings: [],
  citations: {},
  disclosures: ["SYNTHETIC TEST DATA"],
  data_gaps: [],
};

describe("RunSummary", () => {
  it.effect("decodes a run row and its timestamps", () =>
    Effect.gen(function* () {
      const summary = yield* Schema.decodeUnknownEffect(RunSummary)(runSummary);
      assert.strictEqual(summary.state, "complete");
      assert.isDefined(summary.started_at);
      assert.isTrue(DateTime.isDateTime(summary.started_at));
      assert.strictEqual(summary.step_count, 1);
    }),
  );

  it.effect("rejects a row without a state", () =>
    Effect.gen(function* () {
      const { state: _state, ...broken } = runSummary;
      const result = yield* Effect.exit(
        Schema.decodeUnknownEffect(RunSummary)(broken),
      );
      assert.strictEqual(result._tag, "Failure");
    }),
  );
});

const batchSummary = {
  mode: "agent",
  model: "bedrock",
  unlabelled_count: 3,
  run_id: "batch-1",
  state: "complete",
  record_count: 50,
  states: { complete: 42, awaiting_review: 8, failed: 0 },
  verdict_breakdown: { compliant: 30, high_risk: 12, ambiguous: 8 },
  expected_breakdown: { compliant: 30, high_risk: 12, ambiguous: 8 },
  wall_clock_seconds: 123.4,
  average_seconds_per_record: 9.8,
  median_seconds_per_record: 9.1,
  p95_seconds_per_record: 15.2,
  throughput_records_per_second: 0.405,
  total_record_seconds: 490.0,
  cache_stats: { hits: 350, misses: 0, writes: 0, offline_misses: 0 },
  confusion: {
    compliant: { compliant: 30, high_risk: 0, ambiguous: 0 },
    high_risk: { compliant: 0, high_risk: 12, ambiguous: 0 },
    ambiguous: { compliant: 0, high_risk: 0, ambiguous: 8 },
  },
  batch_concurrency: 4,
  sap_actions: { approved: 30, blocked: 12, failed: 0 },
  started_at: "2026-09-11T10:00:00Z",
  finished_at: "2026-09-11T10:02:03Z",
  metrics: {},
};

describe("BatchSummary", () => {
  it.effect("decodes throughput metrics, confusion, and cache stats", () =>
    Effect.gen(function* () {
      const summary =
        yield* Schema.decodeUnknownEffect(BatchSummary)(batchSummary);
      assert.strictEqual(summary.record_count, 50);
      assert.strictEqual(summary.median_seconds_per_record, 9.1);
      assert.strictEqual(summary.throughput_records_per_second, 0.405);
      assert.strictEqual(summary.confusion.ambiguous?.ambiguous, 8);
      assert.strictEqual(summary.cache_stats?.offline_misses, 0);
      assert.strictEqual(summary.batch_concurrency, 4);
      assert.strictEqual(summary.sap_actions.blocked, 12);
      assert.strictEqual(summary.mode, "agent");
      assert.strictEqual(summary.model, "bedrock");
      assert.strictEqual(summary.unlabelled_count, 3);
    }),
  );

  it.effect("requires mode, model and unlabelled_count", () =>
    Effect.gen(function* () {
      const { mode: _mode, ...withoutMode } = batchSummary;
      const { unlabelled_count: _unlabelled, ...withoutCount } = batchSummary;
      for (const body of [withoutMode, withoutCount]) {
        const failure = yield* Effect.flip(
          Schema.decodeUnknownEffect(BatchSummary)(body),
        );
        assert.isDefined(failure);
      }
    }),
  );
});

describe("RunDetail", () => {
  it.effect("decodes the full dossier with a withheld/pending shape", () =>
    Effect.gen(function* () {
      const detail = yield* Schema.decodeUnknownEffect(RunDetail)({
        ...runSummary,
        disclosures: ["SYNTHETIC TEST DATA"],
        verification: null,
        assessment: {
          record_id: "REC-001",
          supplier_id: "SUP-001",
          polygon_id: "POLY-001",
          run_state: "complete",
          expected_archetype: "compliant",
          expected_signal: null,
          expected_ambiguity: null,
          fingerprint: "abc123",
          pending: false,
          assessment,
        },
        pending_assessment: null,
        review: null,
        sap_action: sapAction,
        steps: [step, sapStep],
        dds: {
          released: true,
          schema_version: "eudr-is-v3",
          created_at: "2026-09-11T10:00:01Z",
        },
      });
      assert.strictEqual(detail.assessment?.assessment.verdict, "compliant");
      assert.strictEqual(detail.steps[0]?.name, "queued");
      assert.strictEqual(detail.steps[1]?.kind, "sap");
      assert.strictEqual(detail.sap_action?.status, "approved");
      assert.strictEqual(detail.sap_action?.real, false);
      assert.isTrue(detail.dds?.released);
    }),
  );
});

describe("TraceStep", () => {
  const retaskStep = {
    step_id: "STEP-009",
    kind: "retask",
    name: "legality_analyst",
    detail: "check concession overlap and permit coverage for polygon PLY-001",
    at: "2026-09-11T10:00:00Z",
    payload: { reason: "signals: peat_overlap", ordinal: 2 },
  };

  it.effect("decodes a re-task step", () =>
    Effect.gen(function* () {
      const decoded = yield* Schema.decodeUnknownEffect(TraceStep)(retaskStep);
      assert.strictEqual(decoded.kind, "retask");
      assert.strictEqual(decoded.payload.ordinal, 2);
    }),
  );

  it.effect("still rejects an unknown trace kind", () =>
    Effect.gen(function* () {
      const failure = yield* Effect.flip(
        Schema.decodeUnknownEffect(TraceStep)({ ...retaskStep, kind: "bogus" }),
      );
      assert.isDefined(failure);
    }),
  );
});

describe("RunEvent", () => {
  it.effect("decodes a step event", () =>
    Effect.gen(function* () {
      const event = yield* Schema.decodeUnknownEffect(RunEvent)({
        event: "step",
        data: step,
      });
      assert.strictEqual(event.event, "step");
      if (event.event === "step") {
        assert.strictEqual(event.data.step_id, "STEP-001");
      }
    }),
  );

  it.effect("decodes a progress event with live timing", () =>
    Effect.gen(function* () {
      const event = yield* Schema.decodeUnknownEffect(RunEvent)({
        event: "progress",
        data: {
          run_id: "batch-1",
          total: 50,
          completed: 12,
          failed: 0,
          awaiting_review: 1,
          verdict_breakdown: { compliant: 10, high_risk: 1, ambiguous: 1 },
          elapsed_seconds: 42.5,
        },
      });
      assert.strictEqual(event.event, "progress");
      if (event.event === "progress") {
        assert.strictEqual(event.data.total, 50);
        assert.strictEqual(event.data.elapsed_seconds, 42.5);
      }
    }),
  );

  it.effect("decodes a batch snapshot that replays progress", () =>
    Effect.gen(function* () {
      const event = yield* Schema.decodeUnknownEffect(RunEvent)({
        event: "snapshot",
        data: {
          run_id: "batch-1",
          kind: "batch",
          state: "complete",
          record_id: null,
          parent_run_id: null,
          verdict: null,
          score: null,
          dds_released: false,
          progress: {
            run_id: "batch-1",
            total: 50,
            completed: 42,
            failed: 0,
            awaiting_review: 8,
            verdict_breakdown: { compliant: 30, high_risk: 12, ambiguous: 8 },
            elapsed_seconds: 131.2,
          },
        },
      });
      assert.strictEqual(event.event, "snapshot");
      if (event.event === "snapshot") {
        assert.strictEqual(event.data.progress?.awaiting_review, 8);
        assert.strictEqual(event.data.progress?.elapsed_seconds, 131.2);
      }
    }),
  );
});

describe("decodeRunEventStream", () => {
  const encoder = new TextEncoder();

  it.effect("parses SSE frames into typed events", () =>
    Effect.gen(function* () {
      const wire = [
        `event: snapshot\ndata: ${JSON.stringify({
          run_id: "run-1",
          kind: "scenario",
          state: "running",
          record_id: "REC-001",
          parent_run_id: null,
          verdict: null,
          score: null,
          dds_released: false,
        })}\n\n`,
        `event: step\ndata: ${JSON.stringify(step)}\n\n`,
        `event: done\ndata: ${JSON.stringify({ run_id: "run-1", state: "complete" })}\n\n`,
      ].join("");
      const events = yield* decodeRunEventStream(
        Stream.make(encoder.encode(wire)),
      ).pipe(Stream.runCollect);
      assert.deepStrictEqual(
        [...events].map((event) => event.event),
        ["snapshot", "step", "done"],
      );
    }),
  );

  it.effect("fails typed on a malformed event payload", () =>
    Effect.gen(function* () {
      const exit = yield* decodeRunEventStream(
        Stream.make(encoder.encode("event: step\ndata: {}\n\n")),
      ).pipe(Stream.runCollect, Effect.exit);
      assert.strictEqual(exit._tag, "Failure");
    }),
  );
});

describe("adverseMediaFromSteps", () => {
  const report = {
    subject: "PT Sumber",
    country: "ID",
    status: "success",
    summary: "One simulated finding.",
    findings: [
      {
        claim: "Simulated dispute.",
        citations: [
          { url: "https://example.org/x", title: "Simulated", published: null },
        ],
      },
    ],
    model: "stub",
    synthetic: true,
    disclosure: "Simulated adverse-media result; no web search was performed.",
    cached: false,
    error: null,
  };
  const step = (
    payload: Record<string, unknown>,
    name = "search_adverse_media",
  ) =>
    Schema.decodeUnknownSync(TraceStep)({
      step_id: "STEP-011",
      kind: "tool",
      name,
      detail: "SUP-001: 1 cited finding(s)",
      at: "2026-10-10T09:00:00Z",
      payload,
    });

  it("decodes the report from the media step", () => {
    const decoded = adverseMediaFromSteps([
      step({ supplier_id: "SUP-001", status: "ok", report }),
    ]);
    assert.strictEqual(
      decoded?.findings[0]?.citations[0]?.url,
      "https://example.org/x",
    );
    assert.isTrue(decoded?.synthetic);
  });

  it("returns null when the layer was off or the payload is malformed", () => {
    assert.isNull(adverseMediaFromSteps([]));
    assert.isNull(
      adverseMediaFromSteps([step({ report }, "get_legality_record")]),
    );
    assert.isNull(adverseMediaFromSteps([step({ report: { subject: 1 } })]));
  });
});

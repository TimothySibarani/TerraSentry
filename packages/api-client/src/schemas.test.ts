import { assert, describe, it } from "@effect/vitest";
import { DateTime, Effect, Schema, Stream } from "effect";

import { decodeRunEventStream } from "./client";
import { HealthResponse, RunDetail, RunEvent, RunSummary } from "./schemas";

describe("HealthResponse", () => {
  it.effect("decodes the API health payload", () =>
    Effect.gen(function* () {
      const health = yield* Schema.decodeUnknownEffect(HealthResponse)({
        status: "ok",
        offline: false,
        fixtures_loaded: 0,
      });
      assert.strictEqual(health.status, "ok");
      assert.strictEqual(health.offline, false);
      assert.strictEqual(health.fixtures_loaded, 0);
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
        steps: [step],
        dds: {
          released: true,
          schema_version: "eudr-is-v3",
          created_at: "2026-09-11T10:00:01Z",
        },
      });
      assert.strictEqual(detail.assessment?.assessment.verdict, "compliant");
      assert.strictEqual(detail.steps[0]?.name, "queued");
      assert.isTrue(detail.dds?.released);
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

  it.effect("decodes a progress event", () =>
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
        },
      });
      assert.strictEqual(event.event, "progress");
      if (event.event === "progress") {
        assert.strictEqual(event.data.total, 50);
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

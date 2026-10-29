import { assert, describe, it } from "@effect/vitest";
import { Effect, Fiber, Layer } from "effect";
import { TestClock } from "effect/testing";
import {
  HttpClient,
  type HttpClientRequest,
  HttpClientResponse,
} from "effect/unstable/http";

import { ApiClient } from "./client";
import { ApiClientError } from "./errors";

type Handler = (
  request: HttpClientRequest.HttpClientRequest,
  url: URL,
) => Response;

function stubLayer(handler: Handler): Layer.Layer<HttpClient.HttpClient> {
  return Layer.succeed(
    HttpClient.HttpClient,
    HttpClient.make((request, url) =>
      Effect.sync(() =>
        HttpClientResponse.fromWeb(request, handler(request, url)),
      ),
    ),
  );
}

const runSummary = {
  run_id: "run-1",
  kind: "scenario",
  state: "queued",
  record_id: "REC-001",
  supplier_id: "SUP-001",
  polygon_id: "POLY-001",
  parent_run_id: null,
  model: "scripted",
  erp_mode: "auto",
  summary: "",
  error: null,
  verdict: null,
  score: null,
  expected_archetype: null,
  step_count: 0,
  started_at: null,
  finished_at: null,
  elapsed_seconds: null,
  created_at: "2026-09-11T10:00:00Z",
  metrics: {},
};

const runDetail = {
  ...runSummary,
  disclosures: [],
  verification: null,
  assessment: null,
  pending_assessment: null,
  review: null,
  sap_action: null,
  steps: [],
  dds: null,
};

const batchSummaryBody = {
  run_id: "batch-1",
  state: "queued",
  mode: "agent",
  model: "sap",
  record_count: 10,
  unlabelled_count: 3,
  states: {},
  verdict_breakdown: {},
  expected_breakdown: {},
  wall_clock_seconds: null,
  average_seconds_per_record: null,
  median_seconds_per_record: null,
  p95_seconds_per_record: null,
  throughput_records_per_second: null,
  total_record_seconds: null,
  cache_stats: null,
  confusion: {},
  batch_concurrency: null,
  sap_actions: {},
  started_at: null,
  finished_at: null,
  metrics: {},
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function apiLayer(handler: Handler) {
  return ApiClient.layer("http://terrasentry.test", stubLayer(handler));
}

describe("ApiClient", () => {
  it.live("retries transient reads but attempts transient writes once", () => {
    let calls = 0;
    return Effect.gen(function* () {
      const api = yield* ApiClient;
      yield* api.getRun("run-1");
      assert.strictEqual(calls, 2);
      calls = 0;
      const error = yield* api
        .createRun({ record_id: "REC-001" })
        .pipe(Effect.flip);
      assert.strictEqual(error.status, 503);
      assert.strictEqual(calls, 1);
    }).pipe(
      Effect.provide(
        apiLayer((request) => {
          calls++;
          return request.method === "POST" || calls === 1
            ? jsonResponse({ detail: "temporarily unavailable" }, 503)
            : jsonResponse(runDetail);
        }),
      ),
    );
  });
  it.effect("filters the run list by state and caps the page size", () =>
    Effect.gen(function* () {
      const api = yield* ApiClient;
      const held = yield* api.listRuns({
        state: "awaiting_review",
        limit: 200,
      });
      assert.deepStrictEqual(
        held.map((run) => run.run_id),
        ["run-1"],
      );
      const all = yield* api.listRuns();
      assert.strictEqual(all.length, 1);
    }).pipe(
      Effect.provide(
        apiLayer((request, url) => {
          assert.strictEqual(request.method, "GET");
          const wanted =
            url.search === "" ? "" : "?state=awaiting_review&limit=200";
          assert.strictEqual(url.search, wanted);
          return jsonResponse([runSummary]);
        }),
      ),
    ),
  );
  it.effect(
    "cancels a run and confirms its ERP action with bodyless POSTs",
    () =>
      Effect.gen(function* () {
        const api = yield* ApiClient;
        const cancelled = yield* api.cancelRun("run-1");
        assert.strictEqual(cancelled.run_id, "run-1");
        const action = yield* api.confirmErpAction("run-1");
        assert.strictEqual(action.status, "blocked");
        assert.isTrue(action.purchasing_block);
      }).pipe(
        Effect.provide(
          apiLayer((request, url) => {
            assert.strictEqual(request.method, "POST");
            if (url.pathname === "/runs/run-1/cancel") {
              return jsonResponse(runSummary, 202);
            }
            assert.strictEqual(url.pathname, "/runs/run-1/erp-action");
            return jsonResponse({
              run_id: "run-1",
              supplier_id: "SUP-001",
              vendor_id: "SUP-001",
              mode: "stub",
              status: "blocked",
              purchasing_block: true,
              real: false,
              external_reference: null,
              error: null,
              performed_at: "2026-10-13T00:00:00Z",
            });
          }),
        ),
      ),
  );
  it.effect("GETs and decodes a typed health response", () =>
    Effect.gen(function* () {
      const api = yield* ApiClient;
      const health = yield* api.getHealth();
      assert.strictEqual(health.status, "ok");
    }).pipe(
      Effect.provide(
        apiLayer((request, url) => {
          assert.strictEqual(request.method, "GET");
          assert.strictEqual(url.href, "http://terrasentry.test/health");
          return jsonResponse({
            status: "ok",
            offline: false,
            fixtures_loaded: 0,
            sap_mode: "stub",
            sap_real: false,
            aicore_configured: false,
            adverse_media_mode: "off",
            default_model: "scripted",
            gfw_configured: true,
            firms_configured: true,
            auth_enabled: false,
          });
        }),
      ),
    ),
  );

  it.effect("POSTs the run request as JSON", () =>
    Effect.gen(function* () {
      const api = yield* ApiClient;
      const run = yield* api.createRun({ record_id: "REC-001" });
      assert.strictEqual(run.run_id, "run-1");
    }).pipe(
      Effect.provide(
        apiLayer((request, url) => {
          assert.strictEqual(request.method, "POST");
          assert.strictEqual(url.href, "http://terrasentry.test/runs");
          assert.strictEqual(request.body._tag, "Uint8Array");
          if (request.body._tag === "Uint8Array") {
            assert.deepStrictEqual(JSON.parse(request.body.text ?? ""), {
              record_id: "REC-001",
            });
          }
          return jsonResponse(runSummary, 202);
        }),
      ),
    ),
  );

  it.effect("POSTs an agent batch with its mode and model", () =>
    Effect.gen(function* () {
      const api = yield* ApiClient;
      const batch = yield* api.createBatchRun({
        size: 10,
        mode: "agent",
        model: "sap",
      });
      assert.strictEqual(batch.mode, "agent");
      assert.strictEqual(batch.model, "sap");
      assert.strictEqual(batch.unlabelled_count, 3);
    }).pipe(
      Effect.provide(
        apiLayer((request, url) => {
          assert.strictEqual(url.href, "http://terrasentry.test/batch-runs");
          if (request.body._tag === "Uint8Array") {
            assert.deepStrictEqual(JSON.parse(request.body.text ?? ""), {
              size: 10,
              mode: "agent",
              model: "sap",
            });
          }
          return jsonResponse(batchSummaryBody, 202);
        }),
      ),
    ),
  );

  it.effect("omits the model from a screening batch request", () =>
    Effect.gen(function* () {
      const api = yield* ApiClient;
      yield* api.createBatchRun({ size: 50, mode: "screening" });
    }).pipe(
      Effect.provide(
        apiLayer((request) => {
          if (request.body._tag === "Uint8Array") {
            const sent = JSON.parse(request.body.text ?? "");
            assert.deepStrictEqual(sent, { size: 50, mode: "screening" });
            assert.isFalse("model" in sent);
          }
          return jsonResponse(
            { ...batchSummaryBody, mode: "screening", model: null },
            202,
          );
        }),
      ),
    ),
  );

  it.effect("URL-encodes path parameters", () =>
    Effect.gen(function* () {
      const api = yield* ApiClient;
      const run = yield* api.getRun("run 1/2");
      assert.strictEqual(run.run_id, "run-1");
    }).pipe(
      Effect.provide(
        apiLayer((_request, url) => {
          assert.strictEqual(url.pathname, "/runs/run%201%2F2");
          return jsonResponse(runDetail);
        }),
      ),
    ),
  );

  it.effect("maps a non-2xx response to ApiClientError", () =>
    Effect.gen(function* () {
      const api = yield* ApiClient;
      const error = yield* api.getHealth().pipe(Effect.flip);
      assert.instanceOf(error, ApiClientError);
      assert.strictEqual(error.operation, "getHealth");
      assert.strictEqual(error.status, 404);
    }).pipe(
      Effect.provide(apiLayer(() => jsonResponse({ detail: "no run" }, 404))),
    ),
  );

  it.effect("surfaces 422 field issues on intake errors", () =>
    Effect.gen(function* () {
      const api = yield* ApiClient;
      const error = yield* api
        .validateGeometry({ geometry: { type: "Point", coordinates: [0, 0] } })
        .pipe(Effect.flip);
      assert.strictEqual(error.status, 422);
      assert.deepStrictEqual(error.issues, [
        {
          field: "plot.declared_area_ha",
          message: "a point plot needs a declared area (at most 4 ha)",
        },
      ]);
    }).pipe(
      Effect.provide(
        apiLayer(() =>
          jsonResponse(
            {
              detail: [
                {
                  loc: ["body", "plot", "declared_area_ha"],
                  msg: "a point plot needs a declared area (at most 4 ha)",
                  type: "intake",
                },
              ],
            },
            422,
          ),
        ),
      ),
    ),
  );

  it.effect("sends a bearer token when configured", () =>
    Effect.gen(function* () {
      const api = yield* ApiClient;
      yield* api.getHealth().pipe(Effect.ignore);
    }).pipe(
      Effect.provide(
        ApiClient.layer(
          "http://terrasentry.test",
          stubLayer((request) => {
            assert.strictEqual(
              request.headers.authorization,
              "Bearer demo-token",
            );
            return jsonResponse({ detail: "stop" }, 404);
          }),
          "demo-token",
        ),
      ),
    ),
  );

  it.effect("fails a stalled request with an unreachable-API error", () =>
    Effect.gen(function* () {
      const stalled = Layer.succeed(
        HttpClient.HttpClient,
        HttpClient.make(() => Effect.never),
      );
      const fiber = yield* Effect.gen(function* () {
        const api = yield* ApiClient;
        return yield* api.getHealth();
      }).pipe(
        Effect.flip,
        Effect.provide(ApiClient.layer("http://terrasentry.test", stalled)),
        Effect.forkChild,
      );
      yield* TestClock.adjust("11 seconds");
      const error = yield* Fiber.join(fiber);
      assert.instanceOf(error, ApiClientError);
      assert.strictEqual(error.status, null);
      assert.strictEqual(error.operation, "getHealth");
    }),
  );
});

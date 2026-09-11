import { assert, describe, it } from "@effect/vitest";
import { Effect, Layer } from "effect";
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
  steps: [],
  dds: null,
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
});

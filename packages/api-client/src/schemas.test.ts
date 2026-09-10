import { assert, describe, it } from "@effect/vitest";
import { Effect, Schema } from "effect";

import { HealthResponse } from "./schemas";

describe("HealthResponse", () => {
  it.effect("decodes the API health payload", () =>
    Effect.gen(function* () {
      const health = yield* Schema.decodeUnknownEffect(HealthResponse)({
        status: "ok",
      });
      assert.strictEqual(health.status, "ok");
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

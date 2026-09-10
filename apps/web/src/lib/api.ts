import { ApiClient } from "@terrasentry/api-client";
import type { Effect } from "effect";

import { apiRuntime } from "./runtime";

export function runApi<A, E>(
	f: (api: ApiClient["Service"]) => Effect.Effect<A, E>,
): Promise<A> {
	return apiRuntime.runPromise(ApiClient.use(f));
}

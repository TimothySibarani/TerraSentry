import { Layer, ManagedRuntime } from "effect";
import { FetchHttpClient } from "effect/unstable/http";

import { ApiClient } from "./client";

export function createApiRuntime(baseUrl: string, token?: string) {
  return ManagedRuntime.make(
    ApiClient.layer(baseUrl, FetchHttpClient.layer, token),
    { memoMap: Layer.makeMemoMapUnsafe() },
  );
}

export type ApiRuntime = ReturnType<typeof createApiRuntime>;

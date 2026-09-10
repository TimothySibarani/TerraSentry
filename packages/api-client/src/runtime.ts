import { Layer, ManagedRuntime } from "effect";

import { ApiClient } from "./client";

export function createApiRuntime(baseUrl: string) {
  return ManagedRuntime.make(ApiClient.layer(baseUrl), {
    memoMap: Layer.makeMemoMapUnsafe(),
  });
}

export type ApiRuntime = ReturnType<typeof createApiRuntime>;

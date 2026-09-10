import { Context, Effect, flow, Layer, Schedule } from "effect";
import {
  FetchHttpClient,
  HttpClient,
  HttpClientRequest,
  HttpClientResponse,
} from "effect/unstable/http";

import { ApiClientError } from "./errors";
import { HealthResponse } from "./schemas";

export class ApiClient extends Context.Service<
  ApiClient,
  {
    getHealth(): Effect.Effect<HealthResponse, ApiClientError>;
  }
>()("terrasentry/api-client/ApiClient") {
  static layer(baseUrl: string) {
    return Layer.effect(
      ApiClient,
      Effect.gen(function* () {
        const http = (yield* HttpClient.HttpClient).pipe(
          HttpClient.mapRequest(
            flow(
              HttpClientRequest.prependUrl(baseUrl),
              HttpClientRequest.acceptJson,
            ),
          ),
          HttpClient.filterStatusOk,
          HttpClient.retryTransient({
            schedule: Schedule.exponential(100),
            times: 3,
          }),
        );

        const getHealth = Effect.fn("ApiClient.getHealth")(function* () {
          return yield* http.get("/health").pipe(
            Effect.flatMap(HttpClientResponse.schemaBodyJson(HealthResponse)),
            Effect.mapError(
              (cause) => new ApiClientError({ operation: "getHealth", cause }),
            ),
          );
        });

        return ApiClient.of({ getHealth });
      }),
    ).pipe(Layer.provide(FetchHttpClient.layer));
  }
}

import { Context, Effect, flow, Layer, Schedule, Schema, Stream } from "effect";
import { Sse } from "effect/unstable/encoding";
import {
  FetchHttpClient,
  HttpClient,
  HttpClientError,
  HttpClientRequest,
  HttpClientResponse,
} from "effect/unstable/http";

import { ApiClientError, type FieldIssue } from "./errors";
import {
  type BatchCreateRequest,
  BatchSummary,
  type DecisionRequest,
  EvidenceEntry,
  type GeometryCheckRequest,
  GeometryReport,
  HealthResponse,
  ImportResult,
  RecordOut,
  type RecordSubmission,
  type RunCreateRequest,
  RunDetail,
  RunEvent,
  RunSummary,
  type SapBlockRequest,
  type SapStatusRequest,
  SapVendorOut,
  SupplierDetail,
  SupplierOut,
  ValidationErrorBody,
} from "./schemas";

/** Map FastAPI `detail[]` to dotted field paths (`["body","plot","geometry"]` → `plot.geometry`). */
export const fieldIssues = (
  body: ValidationErrorBody,
): ReadonlyArray<FieldIssue> =>
  body.detail.map((item) => ({
    field: item.loc
      .filter((part, index) => !(index === 0 && part === "body"))
      .join("."),
    message: item.msg,
  }));

export const decodeRunEventStream = <E, R>(
  stream: Stream.Stream<Uint8Array, E, R>,
  operation = "streamRun",
) =>
  stream.pipe(
    Stream.decodeText(),
    Stream.pipeThroughChannel(Sse.decodeDataSchema(Schema.Unknown)),
    Stream.mapEffect((frame) =>
      Schema.decodeUnknownEffect(RunEvent)({
        event: frame.event,
        data: frame.data,
      }),
    ),
    Stream.mapError(
      (cause) => new ApiClientError({ operation, cause, status: null }),
    ),
  );

export class ApiClient extends Context.Service<
  ApiClient,
  {
    getHealth(): Effect.Effect<HealthResponse, ApiClientError>;
    listSuppliers(): Effect.Effect<ReadonlyArray<SupplierOut>, ApiClientError>;
    getSupplier(
      supplierId: string,
    ): Effect.Effect<SupplierDetail, ApiClientError>;
    createRun(
      payload: RunCreateRequest,
    ): Effect.Effect<RunSummary, ApiClientError>;
    listRuns(): Effect.Effect<ReadonlyArray<RunSummary>, ApiClientError>;
    getRun(runId: string): Effect.Effect<RunDetail, ApiClientError>;
    getRunEvidence(
      runId: string,
    ): Effect.Effect<ReadonlyArray<EvidenceEntry>, ApiClientError>;
    submitDecision(
      runId: string,
      payload: DecisionRequest,
    ): Effect.Effect<RunSummary, ApiClientError>;
    getRunDds(runId: string): Effect.Effect<unknown, ApiClientError>;
    getRunDdsXml(runId: string): Effect.Effect<string, ApiClientError>;
    createBatchRun(
      payload: BatchCreateRequest,
    ): Effect.Effect<BatchSummary, ApiClientError>;
    listBatchRuns(): Effect.Effect<ReadonlyArray<BatchSummary>, ApiClientError>;
    getBatchRun(runId: string): Effect.Effect<BatchSummary, ApiClientError>;
    getBatchRunRecords(
      runId: string,
    ): Effect.Effect<ReadonlyArray<RunSummary>, ApiClientError>;
    getSapVendor(vendorId: string): Effect.Effect<SapVendorOut, ApiClientError>;
    updateSapVendorStatus(
      vendorId: string,
      payload: SapStatusRequest,
    ): Effect.Effect<SapVendorOut, ApiClientError>;
    setSapPurchasingBlock(
      vendorId: string,
      payload: SapBlockRequest,
    ): Effect.Effect<SapVendorOut, ApiClientError>;
    createRecord(
      payload: RecordSubmission,
    ): Effect.Effect<RecordOut, ApiClientError>;
    validateGeometry(
      payload: GeometryCheckRequest,
    ): Effect.Effect<GeometryReport, ApiClientError>;
    listRecords(): Effect.Effect<ReadonlyArray<RecordOut>, ApiClientError>;
    getRecord(recordId: string): Effect.Effect<RecordOut, ApiClientError>;
    importRecords(
      file: Blob,
      filename: string,
    ): Effect.Effect<ImportResult, ApiClientError>;
    streamRun(
      runId: string,
    ): Effect.Effect<Stream.Stream<RunEvent, ApiClientError>, ApiClientError>;
    streamBatchRun(
      runId: string,
    ): Effect.Effect<Stream.Stream<RunEvent, ApiClientError>, ApiClientError>;
  }
>()("terrasentry/api-client/ApiClient") {
  static layer(
    baseUrl: string,
    client: Layer.Layer<HttpClient.HttpClient> = FetchHttpClient.layer,
    token?: string,
  ) {
    return Layer.effect(
      ApiClient,
      Effect.gen(function* () {
        const http = (yield* HttpClient.HttpClient).pipe(
          HttpClient.mapRequest(
            flow(
              HttpClientRequest.prependUrl(baseUrl),
              HttpClientRequest.acceptJson,
              (request) =>
                token ? HttpClientRequest.bearerToken(request, token) : request,
            ),
          ),
          HttpClient.filterStatusOk,
          HttpClient.retryTransient({
            schedule: Schedule.exponential(100),
            times: 3,
          }),
        );

        const fail = (operation: string) => (cause: unknown) =>
          new ApiClientError({
            operation,
            cause,
            status: HttpClientError.isHttpClientError(cause)
              ? (cause.response?.status ?? null)
              : null,
          });

        const getJson = <S extends Schema.Constraint>(
          operation: string,
          schema: S,
          url: string,
        ) =>
          http
            .get(url)
            .pipe(
              Effect.flatMap(HttpClientResponse.schemaBodyJson(schema)),
              Effect.mapError(fail(operation)),
            );

        // A 422 carries field-level issues; decode them so forms can point at
        // the exact input instead of showing a generic "invalid request".
        const withIssues =
          (operation: string) =>
          (cause: unknown): Effect.Effect<never, ApiClientError> => {
            const response = HttpClientError.isHttpClientError(cause)
              ? cause.response
              : undefined;
            if (response === undefined || response.status !== 422) {
              return Effect.fail(fail(operation)(cause));
            }
            return response.json.pipe(
              Effect.flatMap(Schema.decodeUnknownEffect(ValidationErrorBody)),
              Effect.map(fieldIssues),
              Effect.orElseSucceed(() => [] as ReadonlyArray<FieldIssue>),
              Effect.flatMap((issues) =>
                Effect.fail(
                  new ApiClientError({
                    operation,
                    cause,
                    status: 422,
                    issues,
                  }),
                ),
              ),
            );
          };

        const sendJson = <S extends Schema.Constraint>(
          operation: string,
          schema: S,
          request: HttpClientRequest.HttpClientRequest,
        ) =>
          http.execute(request).pipe(
            Effect.catch(withIssues(operation)),
            Effect.flatMap((response) =>
              HttpClientResponse.schemaBodyJson(schema)(response).pipe(
                Effect.mapError(fail(operation)),
              ),
            ),
          );

        const body = (method: "POST" | "PUT", url: string, payload: unknown) =>
          (method === "POST"
            ? HttpClientRequest.post(url)
            : HttpClientRequest.put(url)
          ).pipe(HttpClientRequest.bodyJsonUnsafe(payload));

        const getHealth = Effect.fn("ApiClient.getHealth")(function* () {
          return yield* getJson("getHealth", HealthResponse, "/health");
        });

        const listSuppliers = Effect.fn("ApiClient.listSuppliers")(
          function* () {
            return yield* getJson(
              "listSuppliers",
              Schema.Array(SupplierOut),
              "/suppliers",
            );
          },
        );

        const getSupplier = Effect.fn("ApiClient.getSupplier")(function* (
          supplierId: string,
        ) {
          return yield* getJson(
            "getSupplier",
            SupplierDetail,
            `/suppliers/${encodeURIComponent(supplierId)}`,
          );
        });

        const createRun = Effect.fn("ApiClient.createRun")(function* (
          payload: RunCreateRequest,
        ) {
          return yield* sendJson(
            "createRun",
            RunSummary,
            body("POST", "/runs", payload),
          );
        });

        const listRuns = Effect.fn("ApiClient.listRuns")(function* () {
          return yield* getJson("listRuns", Schema.Array(RunSummary), "/runs");
        });

        const getRun = Effect.fn("ApiClient.getRun")(function* (runId: string) {
          return yield* getJson(
            "getRun",
            RunDetail,
            `/runs/${encodeURIComponent(runId)}`,
          );
        });

        const getRunEvidence = Effect.fn("ApiClient.getRunEvidence")(function* (
          runId: string,
        ) {
          return yield* getJson(
            "getRunEvidence",
            Schema.Array(EvidenceEntry),
            `/runs/${encodeURIComponent(runId)}/evidence`,
          );
        });

        const submitDecision = Effect.fn("ApiClient.submitDecision")(function* (
          runId: string,
          payload: DecisionRequest,
        ) {
          return yield* sendJson(
            "submitDecision",
            RunSummary,
            body(
              "POST",
              `/runs/${encodeURIComponent(runId)}/decision`,
              payload,
            ),
          );
        });

        const getRunDds = Effect.fn("ApiClient.getRunDds")(function* (
          runId: string,
        ) {
          return yield* getJson(
            "getRunDds",
            Schema.Unknown,
            `/dds/${encodeURIComponent(runId)}`,
          );
        });

        const getRunDdsXml = Effect.fn("ApiClient.getRunDdsXml")(function* (
          runId: string,
        ) {
          const response = yield* http
            .get(`/dds/${encodeURIComponent(runId)}/xml`)
            .pipe(Effect.mapError(fail("getRunDdsXml")));
          return yield* response.text.pipe(
            Effect.mapError(fail("getRunDdsXml")),
          );
        });

        const createBatchRun = Effect.fn("ApiClient.createBatchRun")(function* (
          payload: BatchCreateRequest,
        ) {
          return yield* sendJson(
            "createBatchRun",
            BatchSummary,
            body("POST", "/batch-runs", payload),
          );
        });

        const listBatchRuns = Effect.fn("ApiClient.listBatchRuns")(
          function* () {
            return yield* getJson(
              "listBatchRuns",
              Schema.Array(BatchSummary),
              "/batch-runs",
            );
          },
        );

        const getBatchRun = Effect.fn("ApiClient.getBatchRun")(function* (
          runId: string,
        ) {
          return yield* getJson(
            "getBatchRun",
            BatchSummary,
            `/batch-runs/${encodeURIComponent(runId)}`,
          );
        });

        const getBatchRunRecords = Effect.fn("ApiClient.getBatchRunRecords")(
          function* (runId: string) {
            return yield* getJson(
              "getBatchRunRecords",
              Schema.Array(RunSummary),
              `/batch-runs/${encodeURIComponent(runId)}/records`,
            );
          },
        );

        const getSapVendor = Effect.fn("ApiClient.getSapVendor")(function* (
          vendorId: string,
        ) {
          return yield* getJson(
            "getSapVendor",
            SapVendorOut,
            `/mock-sap/vendors/${encodeURIComponent(vendorId)}`,
          );
        });

        const updateSapVendorStatus = Effect.fn(
          "ApiClient.updateSapVendorStatus",
        )(function* (vendorId: string, payload: SapStatusRequest) {
          return yield* sendJson(
            "updateSapVendorStatus",
            SapVendorOut,
            body(
              "PUT",
              `/mock-sap/vendors/${encodeURIComponent(vendorId)}/status`,
              payload,
            ),
          );
        });

        const setSapPurchasingBlock = Effect.fn(
          "ApiClient.setSapPurchasingBlock",
        )(function* (vendorId: string, payload: SapBlockRequest) {
          return yield* sendJson(
            "setSapPurchasingBlock",
            SapVendorOut,
            body(
              "PUT",
              `/mock-sap/vendors/${encodeURIComponent(vendorId)}/purchasing-block`,
              payload,
            ),
          );
        });

        const createRecord = Effect.fn("ApiClient.createRecord")(function* (
          payload: RecordSubmission,
        ) {
          return yield* sendJson(
            "createRecord",
            RecordOut,
            body("POST", "/records", payload),
          );
        });

        const validateGeometry = Effect.fn("ApiClient.validateGeometry")(
          function* (payload: GeometryCheckRequest) {
            return yield* sendJson(
              "validateGeometry",
              GeometryReport,
              body("POST", "/records/validate-geometry", payload),
            );
          },
        );

        const listRecords = Effect.fn("ApiClient.listRecords")(function* () {
          return yield* getJson(
            "listRecords",
            Schema.Array(RecordOut),
            "/records",
          );
        });

        const getRecord = Effect.fn("ApiClient.getRecord")(function* (
          recordId: string,
        ) {
          return yield* getJson(
            "getRecord",
            RecordOut,
            `/records/${encodeURIComponent(recordId)}`,
          );
        });

        const importRecords = Effect.fn("ApiClient.importRecords")(function* (
          file: Blob,
          filename: string,
        ) {
          const form = new FormData();
          form.append("file", file, filename);
          return yield* sendJson(
            "importRecords",
            ImportResult,
            HttpClientRequest.post("/records/import").pipe(
              HttpClientRequest.bodyFormData(form),
            ),
          );
        });

        const streamRun = Effect.fn("ApiClient.streamRun")(function* (
          runId: string,
        ) {
          const response = yield* http
            .get(`/runs/${encodeURIComponent(runId)}/stream`)
            .pipe(Effect.mapError(fail("streamRun")));
          return decodeRunEventStream(response.stream);
        });

        const streamBatchRun = Effect.fn("ApiClient.streamBatchRun")(function* (
          runId: string,
        ) {
          const response = yield* http
            .get(`/batch-runs/${encodeURIComponent(runId)}/stream`)
            .pipe(Effect.mapError(fail("streamBatchRun")));
          return decodeRunEventStream(response.stream, "streamBatchRun");
        });

        return ApiClient.of({
          getHealth,
          listSuppliers,
          getSupplier,
          createRun,
          listRuns,
          getRun,
          getRunEvidence,
          submitDecision,
          getRunDds,
          getRunDdsXml,
          createBatchRun,
          listBatchRuns,
          getBatchRun,
          getBatchRunRecords,
          getSapVendor,
          updateSapVendorStatus,
          setSapPurchasingBlock,
          createRecord,
          validateGeometry,
          listRecords,
          getRecord,
          importRecords,
          streamRun,
          streamBatchRun,
        });
      }),
    ).pipe(Layer.provide(client));
  }
}

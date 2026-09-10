import { Schema } from "effect";

export class HealthResponse extends Schema.Class<HealthResponse>(
  "terrasentry/api-client/HealthResponse",
)({
  status: Schema.String,
}) {}

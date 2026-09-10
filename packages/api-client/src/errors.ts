import { Schema } from "effect";

export class ApiClientError extends Schema.TaggedError<ApiClientError>()(
  "ApiClientError",
  {
    operation: Schema.String,
    cause: Schema.Defect(),
  },
) {}

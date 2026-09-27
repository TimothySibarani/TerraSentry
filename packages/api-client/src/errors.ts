import { Schema } from "effect";

/** One field-level validation problem from a 422 response. */
export const FieldIssue = Schema.Struct({
  /** Dotted path without the leading `body`, e.g. `plot.geometry`. */
  field: Schema.String,
  message: Schema.String,
});
export type FieldIssue = typeof FieldIssue.Type;

export class ApiClientError extends Schema.TaggedError<ApiClientError>()(
  "ApiClientError",
  {
    operation: Schema.String,
    cause: Schema.Defect(),
    status: Schema.NullOr(Schema.Number),
    /** Present on 422 responses so forms can mark the offending field. */
    issues: Schema.optionalKey(Schema.Array(FieldIssue)),
  },
) {}

import { ApiClientError } from "@terrasentry/api-client";

/** Mirrors `ApiClientError.message`. */
const MESSAGE = /^(\w+): (?:could not reach the API|HTTP (\d{3}))$/;

export interface ApiErrorInfo {
	operation: string;
	/** HTTP status, or `null` when the API could not be reached. */
	status: number | null;
}

/**
 * Recognise an `ApiClientError`, including one that crossed the SSR boundary.
 * Loader errors are serialised on the server and lose their prototype, so
 * `instanceof` alone misses them.
 */
export function asApiError(error: unknown): ApiErrorInfo | null {
	if (error instanceof ApiClientError) {
		return { operation: error.operation, status: error.status };
	}
	if (typeof error !== "object" || error === null) {
		return null;
	}
	// A hydrated loader error is a plain `Error` carrying `ApiClientError.message`.
	const parsed = MESSAGE.exec(String((error as { message?: unknown }).message));
	if (parsed !== null) {
		return {
			operation: parsed[1] ?? "API",
			status: parsed[2] === undefined ? null : Number(parsed[2]),
		};
	}
	const shape = error as Record<string, unknown>;
	if (shape._tag !== "ApiClientError" && shape.name !== "ApiClientError") {
		return null;
	}
	return {
		operation: typeof shape.operation === "string" ? shape.operation : "API",
		status: typeof shape.status === "number" ? shape.status : null,
	};
}

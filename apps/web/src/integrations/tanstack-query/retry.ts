import { ApiClientError } from "@terrasentry/api-client";

const MAX_ATTEMPTS = 3;

/**
 * Retry transient failures (transport errors and 5xx) but never replay a
 * request the API explicitly rejected (4xx). The Effect client already retries
 * transient failures internally, so this only governs the query cache.
 */
export function shouldRetryQuery(
	failureCount: number,
	error: unknown,
): boolean {
	if (error instanceof ApiClientError && error.status !== null) {
		return error.status >= 500 && failureCount < MAX_ATTEMPTS;
	}
	return failureCount < MAX_ATTEMPTS;
}

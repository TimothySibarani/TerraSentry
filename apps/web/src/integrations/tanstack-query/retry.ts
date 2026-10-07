import { asApiError } from "#/lib/api-error";

const MAX_ATTEMPTS = 3;

/**
 * Retry transient failures (5xx) but never replay a request the API
 * explicitly rejected (4xx). The Effect client already retries transport
 * errors and bounds each request with a timeout, so an unreachable API is
 * retried at most once here instead of waiting out another backoff series.
 */
export function shouldRetryQuery(
	failureCount: number,
	error: unknown,
): boolean {
	const api = asApiError(error);
	if (api !== null) {
		if (api.status === null) {
			return failureCount < 1;
		}
		return api.status >= 500 && failureCount < MAX_ATTEMPTS;
	}
	return failureCount < MAX_ATTEMPTS;
}

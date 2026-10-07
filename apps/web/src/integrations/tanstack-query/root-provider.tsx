import { QueryClient } from "@tanstack/react-query";

import { shouldRetryQuery } from "./retry";

export function getContext() {
	const queryClient = new QueryClient({
		defaultOptions: {
			queries: {
				// The server render should surface an unreachable API immediately.
				retry: typeof window === "undefined" ? false : shouldRetryQuery,
			},
		},
	});

	return {
		queryClient,
	};
}

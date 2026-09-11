import { QueryClient } from "@tanstack/react-query";

import { shouldRetryQuery } from "./retry";

export function getContext() {
	const queryClient = new QueryClient({
		defaultOptions: {
			queries: {
				retry: shouldRetryQuery,
			},
		},
	});

	return {
		queryClient,
	};
}

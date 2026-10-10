import {
	queryOptions,
	useMutation,
	useQueryClient,
} from "@tanstack/react-query";
import type { OperatorUpdate } from "@terrasentry/api-client";
import { runApi } from "#/lib/api";

export function operatorQuery() {
	return queryOptions({
		queryKey: ["settings", "operator"],
		queryFn: () => runApi((api) => api.getOperator()),
	});
}

export function useSaveOperator() {
	const client = useQueryClient();
	return useMutation({
		mutationFn: (payload: OperatorUpdate) =>
			runApi((api) => api.updateOperator(payload)),
		onSuccess: (saved) => client.setQueryData(operatorQuery().queryKey, saved),
	});
}

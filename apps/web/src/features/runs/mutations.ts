import type {
	BatchCreateRequest,
	DecisionRequest,
	RunCreateRequest,
} from "@terrasentry/api-client";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { runApi } from "#/lib/api";

export function useCreateRun() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (payload: RunCreateRequest) =>
			runApi((api) => api.createRun(payload)),
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: ["runs"] });
		},
	});
}

export function useCreateBatch() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (payload: BatchCreateRequest) =>
			runApi((api) => api.createBatchRun(payload)),
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: ["batch"] });
		},
	});
}

export function useRunDecision(runId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (payload: DecisionRequest) =>
			runApi((api) => api.submitDecision(runId, payload)),
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: ["runs", runId] });
			void queryClient.invalidateQueries({
				queryKey: ["runs", runId, "evidence"],
			});
			void queryClient.invalidateQueries({ queryKey: ["runs", runId, "dds"] });
			void queryClient.invalidateQueries({ queryKey: ["runs"] });
		},
	});
}

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type {
	BatchCreateRequest,
	DecisionRequest,
	RunCreateRequest,
} from "@terrasentry/api-client";

import { runApi } from "#/lib/api";

function invalidateRun(
	queryClient: ReturnType<typeof useQueryClient>,
	runId: string,
) {
	void queryClient.invalidateQueries({ queryKey: ["runs", runId] });
	void queryClient.invalidateQueries({ queryKey: ["runs"] });
	void queryClient.invalidateQueries({ queryKey: ["suppliers"] });
}

export interface BulkDecisionInput {
	runIds: ReadonlyArray<string>;
	decision: DecisionRequest["decision"];
	reviewer: string;
	note: string;
}

export interface BulkDecisionResult {
	succeeded: ReadonlyArray<string>;
	failed: ReadonlyArray<{ runId: string; message: string }>;
}

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

export function useCancelRun(runId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: () => runApi((api) => api.cancelRun(runId)),
		onSuccess: () => invalidateRun(queryClient, runId),
	});
}

export function useDeleteRun() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (runId: string) => runApi((api) => api.deleteRun(runId)),
		onSuccess: (_result, runId) => {
			void queryClient.removeQueries({ queryKey: ["runs", runId] });
			void queryClient.invalidateQueries({ queryKey: ["runs"] });
			void queryClient.invalidateQueries({ queryKey: ["batch"] });
			void queryClient.invalidateQueries({ queryKey: ["suppliers"] });
		},
	});
}

export function useConfirmErpAction(runId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: () => runApi((api) => api.confirmErpAction(runId)),
		onSuccess: () => {
			invalidateRun(queryClient, runId);
			void queryClient.invalidateQueries({
				queryKey: ["runs", runId, "dds"],
			});
		},
	});
}

/**
 * Decide on several held runs one after another. A failure on one run never stops the rest,
 * so a reviewer sees exactly which decisions were recorded.
 */
export function useBulkDecision() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: async (
			input: BulkDecisionInput,
		): Promise<BulkDecisionResult> => {
			const succeeded: string[] = [];
			const failed: Array<{ runId: string; message: string }> = [];
			for (const runId of input.runIds) {
				try {
					await runApi((api) =>
						api.submitDecision(runId, {
							decision: input.decision,
							reviewer: input.reviewer,
							note: input.note,
						}),
					);
					succeeded.push(runId);
				} catch (error) {
					failed.push({
						runId,
						message: error instanceof Error ? error.message : String(error),
					});
				}
			}
			return { succeeded, failed };
		},
		onSettled: () => {
			void queryClient.invalidateQueries({ queryKey: ["runs"] });
			void queryClient.invalidateQueries({ queryKey: ["batch"] });
			void queryClient.invalidateQueries({ queryKey: ["suppliers"] });
		},
	});
}

import { ApiClient } from "@terrasentry/api-client";
import { useQueryClient } from "@tanstack/react-query";
import { Effect, Stream } from "effect";
import { useCallback, useEffect, useReducer, useState } from "react";

import {
	applyRunEvent,
	createRunStreamState,
	isTerminalEvent,
	type RunStreamState,
} from "#/features/runs/stream";
import { apiRuntime } from "#/lib/runtime";

export type BatchStreamStatus = "connecting" | "live" | "closed" | "error";

export function useBatchStream(
	batchRunId: string,
	seed: Partial<RunStreamState>,
) {
	const queryClient = useQueryClient();
	const [state, dispatch] = useReducer(
		applyRunEvent,
		seed,
		createRunStreamState,
	);
	const [status, setStatus] = useState<BatchStreamStatus>("connecting");
	const [error, setError] = useState<unknown>(null);
	const [attempt, setAttempt] = useState(0);

	// biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` intentionally restarts the subscription on reconnect
	useEffect(() => {
		setStatus("connecting");
		setError(null);
		const program = ApiClient.use((api) => api.streamBatchRun(batchRunId)).pipe(
			Effect.flatMap((events) =>
				events.pipe(
					Stream.takeUntil(isTerminalEvent),
					Stream.runForEach((event) =>
						Effect.sync(() => {
							setStatus("live");
							dispatch(event);
						}),
					),
				),
			),
			Effect.tap(() =>
				Effect.sync(() => {
					setStatus("closed");
					void queryClient.invalidateQueries({ queryKey: ["batch"] });
					void queryClient.invalidateQueries({
						queryKey: ["batch", batchRunId],
					});
					void queryClient.invalidateQueries({
						queryKey: ["batch", batchRunId, "records"],
					});
				}),
			),
			Effect.catch((cause) =>
				Effect.sync(() => {
					setError(cause);
					setStatus("error");
				}),
			),
		);
		const controller = new AbortController();
		apiRuntime.runFork(program, { signal: controller.signal });
		return () => {
			controller.abort();
		};
	}, [batchRunId, attempt, queryClient]);

	const reconnect = useCallback(() => setAttempt((count) => count + 1), []);

	return { state, status, error, reconnect };
}

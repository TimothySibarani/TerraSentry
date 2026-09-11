import type { RunEvent, RunState, TraceStep } from "@terrasentry/api-client";

export const TERMINAL_STATES: ReadonlyArray<RunState> = [
	"complete",
	"failed",
	"awaiting_review",
];

export function isTerminalState(state: string | null | undefined): boolean {
	return (
		state !== null &&
		state !== undefined &&
		TERMINAL_STATES.includes(state as RunState)
	);
}

export interface BatchProgress {
	total: number;
	completed: number;
	failed: number;
	awaitingReview: number;
	verdictBreakdown: Record<string, number>;
	elapsedSeconds: number | null;
}

function toBatchProgress(data: {
	total: number;
	completed: number;
	failed: number;
	awaiting_review: number;
	verdict_breakdown: Record<string, number>;
	elapsed_seconds?: number | null;
}): BatchProgress {
	return {
		total: data.total,
		completed: data.completed,
		failed: data.failed,
		awaitingReview: data.awaiting_review,
		verdictBreakdown: data.verdict_breakdown,
		elapsedSeconds: data.elapsed_seconds ?? null,
	};
}

export interface RunStreamState {
	steps: TraceStep[];
	state: RunState | null;
	verdict: string | null;
	score: number | null;
	ddsReleased: boolean;
	progress: BatchProgress | null;
	eventCount: number;
}

export function createRunStreamState(
	seed: Partial<RunStreamState> = {},
): RunStreamState {
	return {
		steps: seed.steps ?? [],
		state: seed.state ?? null,
		verdict: seed.verdict ?? null,
		score: seed.score ?? null,
		ddsReleased: seed.ddsReleased ?? false,
		progress: seed.progress ?? null,
		eventCount: 0,
	};
}

export function mergeStep(steps: TraceStep[], step: TraceStep): TraceStep[] {
	if (steps.some((existing) => existing.step_id === step.step_id)) {
		return steps;
	}
	return [...steps, step];
}

export function applyRunEvent(
	state: RunStreamState,
	event: RunEvent,
): RunStreamState {
	switch (event.event) {
		case "snapshot":
			return {
				...state,
				state: event.data.state,
				verdict: event.data.verdict,
				score: event.data.score,
				ddsReleased: event.data.dds_released,
				progress: event.data.progress
					? toBatchProgress(event.data.progress)
					: state.progress,
				eventCount: state.eventCount + 1,
			};
		case "step":
			return {
				...state,
				steps: mergeStep(state.steps, event.data),
				eventCount: state.eventCount + 1,
			};
		case "state":
		case "done":
			return {
				...state,
				state: event.data.state,
				eventCount: state.eventCount + 1,
			};
		case "progress":
			return {
				...state,
				progress: toBatchProgress(event.data),
				eventCount: state.eventCount + 1,
			};
	}
}

export function isTerminalEvent(event: RunEvent): boolean {
	return (
		event.event === "done" ||
		(event.event === "state" && isTerminalState(event.data.state))
	);
}

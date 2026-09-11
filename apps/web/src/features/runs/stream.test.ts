import { RunEvent, TraceStep } from "@terrasentry/api-client";
import { Schema } from "effect";
import { describe, expect, it } from "vitest";

import {
	applyRunEvent,
	createRunStreamState,
	isTerminalEvent,
	isTerminalState,
	mergeStep,
} from "./stream";

const decodeEvent = Schema.decodeUnknownSync(RunEvent);
const decodeStep = Schema.decodeUnknownSync(TraceStep);

const stepInput = (stepId: string) => ({
	step_id: stepId,
	kind: "tool",
	name: `step ${stepId}`,
	detail: "",
	at: "2026-09-11T10:00:00Z",
	payload: {},
});

const step = (stepId: string) => decodeStep(stepInput(stepId));

const stepEvent = (stepId: string) =>
	decodeEvent({ event: "step", data: stepInput(stepId) });

describe("run stream reducer", () => {
	it("seeds snapshot state, verdict, score, and DDS release", () => {
		const state = applyRunEvent(
			createRunStreamState(),
			decodeEvent({
				event: "snapshot",
				data: {
					run_id: "run-1",
					kind: "scenario",
					state: "running",
					record_id: "REC-001",
					parent_run_id: null,
					verdict: null,
					score: null,
					dds_released: false,
				},
			}),
		);
		expect(state.state).toBe("running");
		expect(state.verdict).toBeNull();
		expect(state.ddsReleased).toBe(false);
	});

	it("dedupes steps by step_id", () => {
		const first = applyRunEvent(createRunStreamState(), stepEvent("STEP-001"));
		const second = applyRunEvent(first, stepEvent("STEP-001"));
		expect(second.steps).toHaveLength(1);
		expect(mergeStep([step("a")], step("a"))).toHaveLength(1);
	});

	it("tracks state transitions and done events", () => {
		const running = applyRunEvent(
			createRunStreamState(),
			decodeEvent({
				event: "state",
				data: { run_id: "run-1", state: "running" },
			}),
		);
		expect(
			isTerminalEvent(
				decodeEvent({
					event: "state",
					data: { run_id: "run-1", state: "running" },
				}),
			),
		).toBe(false);
		const done = applyRunEvent(
			running,
			decodeEvent({
				event: "done",
				data: { run_id: "run-1", state: "complete" },
			}),
		);
		expect(done.state).toBe("complete");
		expect(isTerminalState("complete")).toBe(true);
		expect(isTerminalState("awaiting_review")).toBe(true);
		expect(isTerminalState("failed")).toBe(true);
		expect(isTerminalState("running")).toBe(false);
	});

	it("maps progress frames for batches", () => {
		const state = applyRunEvent(
			createRunStreamState(),
			decodeEvent({
				event: "progress",
				data: {
					run_id: "batch-1",
					total: 50,
					completed: 12,
					failed: 0,
					awaiting_review: 1,
					verdict_breakdown: {
						compliant: 10,
						high_risk: 1,
						ambiguous: 1,
					},
					elapsed_seconds: 42.5,
				},
			}),
		);
		expect(state.progress).toEqual({
			total: 50,
			completed: 12,
			failed: 0,
			awaitingReview: 1,
			verdictBreakdown: { compliant: 10, high_risk: 1, ambiguous: 1 },
			elapsedSeconds: 42.5,
		});
	});

	it("seeds progress from a batch snapshot for late subscribers", () => {
		const state = applyRunEvent(
			createRunStreamState(),
			decodeEvent({
				event: "snapshot",
				data: {
					run_id: "batch-1",
					kind: "batch",
					state: "complete",
					record_id: null,
					parent_run_id: null,
					verdict: null,
					score: null,
					dds_released: false,
					progress: {
						run_id: "batch-1",
						total: 50,
						completed: 42,
						failed: 0,
						awaiting_review: 8,
						verdict_breakdown: { compliant: 30, high_risk: 12, ambiguous: 8 },
						elapsed_seconds: 131.2,
					},
				},
			}),
		);
		expect(state.progress?.awaitingReview).toBe(8);
		expect(state.progress?.elapsedSeconds).toBe(131.2);
	});

	it("treats a terminal state frame as end-of-stream", () => {
		expect(
			isTerminalEvent(
				decodeEvent({
					event: "state",
					data: { run_id: "run-1", state: "awaiting_review" },
				}),
			),
		).toBe(true);
		expect(
			isTerminalEvent(
				decodeEvent({
					event: "done",
					data: { run_id: "run-1", state: "complete" },
				}),
			),
		).toBe(true);
	});
});

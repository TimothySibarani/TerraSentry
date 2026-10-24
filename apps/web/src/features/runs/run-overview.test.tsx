import type { TraceStep } from "@terrasentry/api-client";
import { cleanup, render, screen, within } from "@testing-library/react";
import { DateTime } from "effect";
import { afterEach, expect, it } from "vitest";
import { deriveAgentRun } from "./agent-run";
import { RunOverview } from "./run-overview";

afterEach(cleanup);
const at = DateTime.makeUnsafe("2026-10-24T00:00:00Z");
const steps: TraceStep[] = [
	{
		step_id: "1",
		kind: "run",
		name: "configuration",
		detail: "",
		at,
		payload: {
			task: "Assess",
			models: { orchestrator: "model-a", extraction: "model-b" },
			params: {},
			agents: [],
		},
	},
	{
		step_id: "2",
		kind: "agent",
		name: "supervisor",
		detail: "started",
		at,
		payload: {},
	},
];
it("announces investigation progress and flips to completed on rerender", () => {
	const { rerender } = render(
		<RunOverview
			run={deriveAgentRun(steps, { model: "sap", state: "running" })}
			score={null}
			started={at}
		/>,
	);
	const investigating = screen.getByText("Investigating");
	expect(investigating.getAttribute("aria-current")).toBe("step");
	expect(within(investigating).getByText("In progress")).toBeDefined();
	expect(screen.getByText("orchestrator · model-a")).toBeDefined();
	rerender(
		<RunOverview
			run={deriveAgentRun(steps, { model: "sap", state: "complete" })}
			score={0}
			started={at}
		/>,
	);
	expect(
		within(screen.getByText("Investigating")).getByText("Completed"),
	).toBeDefined();
	expect(screen.getByText("6/6 completed")).toBeDefined();
});
it("shows mode for historical runs", () => {
	render(
		<RunOverview
			run={deriveAgentRun(steps.slice(1), { model: "sap", state: "running" })}
			score={null}
			started={at}
		/>,
	);
	expect(screen.getByText("orchestrator · sap")).toBeDefined();
});

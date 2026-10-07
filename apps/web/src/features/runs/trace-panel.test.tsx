import type { TraceStep } from "@terrasentry/api-client";
import { cleanup, render, screen } from "@testing-library/react";
import { DateTime } from "effect";
import { afterEach, expect, it } from "vitest";
import { TracePanel } from "./trace-panel";

afterEach(cleanup);

function step(
	index: number,
	kind: TraceStep["kind"],
	name: string,
	detail = "",
): TraceStep {
	return {
		step_id: `STEP-${String(index).padStart(3, "0")}`,
		kind,
		name,
		detail,
		at: DateTime.makeUnsafe("2026-10-04T09:00:00Z"),
		payload: {},
	};
}

const reason =
	"check concession overlap and permit coverage for polygon PLY-001. SCREENING_SIGNALS: peat_overlap";

it("highlights a re-task with its reason and an accessible, non-colour cue", () => {
	render(
		<TracePanel
			status="closed"
			steps={[
				step(1, "agent", "legality_analyst", "delegated by supervisor"),
				step(2, "retask", "legality_analyst", reason),
				step(3, "retask", "geospatial_analyst", "get context layers"),
			]}
		/>,
	);
	const rows = screen.getAllByRole("listitem");
	const retaskRow = rows[1] as HTMLElement;
	expect(retaskRow.getAttribute("data-kind")).toBe("retask");
	expect(retaskRow.textContent).toContain("re-task");
	expect(retaskRow.textContent).toContain("Reason:");
	expect(retaskRow.textContent).toContain(reason);
	expect(retaskRow.textContent).toContain("Re-task of legality_analyst");
	expect(rows[0]?.getAttribute("data-kind")).toBe("agent");
});

it("summarises the re-tasks above the trace", () => {
	render(
		<TracePanel
			status="closed"
			steps={[
				step(1, "agent", "legality_analyst"),
				step(2, "retask", "legality_analyst", reason),
				step(3, "retask", "geospatial_analyst", "get context layers"),
			]}
		/>,
	);
	expect(
		screen.getByText("2 re-tasks: legality_analyst, geospatial_analyst"),
	).toBeDefined();
});

it("shows no re-task summary when the Supervisor did not re-task", () => {
	render(
		<TracePanel
			status="closed"
			steps={[step(1, "agent", "legality_analyst", "delegated by supervisor")]}
		/>,
	);
	expect(screen.queryByText(/re-task/)).toBeNull();
});

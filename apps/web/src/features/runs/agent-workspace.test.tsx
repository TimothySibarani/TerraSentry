import type { TraceStep } from "@terrasentry/api-client";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	within,
} from "@testing-library/react";
import { DateTime } from "effect";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { deriveAgentRun } from "./agent-run";
import { AgentWorkspace } from "./agent-workspace";

afterEach(() => {
	cleanup();
	vi.restoreAllMocks();
});
beforeEach(() => {
	vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
		matches: true,
		media: query,
		onchange: null,
		addListener: () => {},
		removeListener: () => {},
		addEventListener: () => {},
		removeEventListener: () => {},
		dispatchEvent: () => true,
	}));
});
const base = DateTime.toEpochMillis(
	DateTime.makeUnsafe("2026-10-24T00:00:00Z"),
);
function step(
	index: number,
	kind: TraceStep["kind"],
	name: string,
	detail = "",
	payload: TraceStep["payload"] = {},
): TraceStep {
	return {
		step_id: `STEP-${index}`,
		kind,
		name,
		detail,
		payload,
		at: DateTime.makeUnsafe(base + index * 1000),
	};
}
const names = [
	"supervisor",
	"geospatial_analyst",
	"thermal_analyst",
	"legality_analyst",
	"assessor",
	"verifier",
	"dds_writer",
];
const steps: TraceStep[] = [
	step(0, "state", "queued"),
	step(1, "run", "configuration", "", {
		task: "Assess REC-001",
		models: { orchestrator: "model-a", extraction: "model-b" },
		params: {},
		agents: names.map((name) => ({
			name,
			role:
				name === "assessor" || name === "dds_writer"
					? "code"
					: name.endsWith("_analyst")
						? "extraction"
						: "orchestrator",
			model: name.endsWith("_analyst") ? "model-b" : "model-a",
			tools: name === "legality_analyst" ? ["check_concession_overlap"] : [],
			system_prompt: "Review evidence",
		})),
	}),
	step(2, "agent", "supervisor", "started"),
	step(3, "agent", "geospatial_analyst", "delegated by supervisor"),
	step(4, "tool", "get_tree_cover_loss"),
	step(5, "report", "geospatial_analyst", "reported", { report: "Found loss" }),
	step(6, "agent", "thermal_analyst", "delegated"),
	step(7, "tool", "get_fire_hotspots"),
	step(8, "report", "thermal_analyst", "reported", { report: "No fire" }),
	step(9, "agent", "legality_analyst", "delegated"),
	step(10, "tool", "get_legality_record"),
	step(11, "report", "legality_analyst", "reported", { report: "Permit read" }),
	step(12, "retask", "legality_analyst", "Check concession holder", {
		agent: "legality_analyst",
		invocation: 2,
		input: "Check concession holder",
		reason: "Check concession holder",
		ordinal: 2,
	}),
	step(13, "tool", "check_concession_overlap", "done", {
		agent: "legality_analyst",
		invocation: 2,
		input: { polygon_id: "PLY-001" },
		result: { preview: "many features", truncated: true },
		duration_ms: 400,
		status: "ok",
	}),
	step(14, "report", "legality_analyst", "reported", {
		report: "Holder differs",
		invocation: 2,
		agent: "legality_analyst",
	}),
	step(15, "agent", "supervisor", "finished"),
	step(16, "run", "assessor"),
	step(17, "writer", "dds_writer"),
	step(18, "state", "awaiting_review"),
];
function mount(
	trace = steps,
	selectedAgent?: string,
	selectedStep?: string,
	state = "awaiting_review",
) {
	const onSelect = vi.fn();
	const run = deriveAgentRun(trace, {
		model: "sap",
		state,
		now: base + 30_000,
	});
	return {
		onSelect,
		...render(
			<AgentWorkspace
				steps={trace}
				run={run}
				model="sap"
				state={state}
				status="closed"
				selectedAgent={selectedAgent}
				selectedStep={selectedStep}
				onSelect={onSelect}
			/>,
		),
	};
}
const label = (name: string) => new RegExp(name.replaceAll("_", " "));
const tree = () => screen.getByRole("tree", { name: "Agents" });

it("lists agents and code nodes in one timeline and inspects re-task inputs and context", () => {
	mount(steps, "legality_analyst");
	for (const name of names)
		expect(
			within(tree()).getByRole("treeitem", { name: label(name) }),
		).toBeDefined();
	const inspector = screen.getByRole("region", {
		name: "legality_analyst inspector",
	});
	expect(within(inspector).getByText("Check concession holder")).toBeDefined();
	fireEvent.click(within(inspector).getByRole("tab", { name: "Context" }));
	expect(within(inspector).getByText("check_concession_overlap")).toBeDefined();
});
it("selects a tool row and shows its input, result and truncation", () => {
	const { onSelect } = mount(steps, "legality_analyst", "STEP-13");
	fireEvent.click(
		within(tree()).getByRole("treeitem", { name: "check_concession_overlap" }),
	);
	expect(onSelect).toHaveBeenCalledWith("legality_analyst", "STEP-13");
	const inspector = screen.getByRole("region", {
		name: "legality_analyst inspector",
	});
	// The input reads as facts: the id, what it resolves to, and the dataset queried.
	expect(within(inspector).getByText("PLY-001")).toBeDefined();
	expect(
		within(inspector).getByText(
			"Plot geometry + declared holder from the run input",
		),
	).toBeDefined();
	expect(within(inspector).getByText("GFW concession layers")).toBeDefined();
	expect(
		within(inspector).getAllByText(/many features/).length,
	).toBeGreaterThan(0);
	expect(within(inspector).getByText(/Result truncated to 4 KB/)).toBeDefined();
});
it("replays at delegation with running parents and pending future agents, then restores the end", () => {
	mount();
	const slider = screen.getByRole("slider", { name: "Replay time" });
	fireEvent.change(slider, { target: { value: String(base + 3000) } });
	const status = (name: string) =>
		within(tree()).getByRole("treeitem", { name: label(name) }).textContent;
	expect(status("supervisor")).toContain("In progress");
	expect(status("geospatial_analyst")).toContain("In progress");
	for (const name of ["thermal_analyst", "legality_analyst", "verifier"])
		expect(status(name)).toContain("Pending");
	expect(
		screen.queryByRole("button", { name: "get_tree_cover_loss span" }),
	).toBeNull();
	fireEvent.change(slider, { target: { value: String(base + 18000) } });
	expect(
		screen.getByRole("button", { name: "check_concession_overlap span" }),
	).toBeDefined();
});
it("renders old traces and explains missing configuration and thinking", () => {
	const old = steps
		.filter((s) => s.name !== "configuration")
		.map((s) => ({ ...s, payload: {} }));
	mount(old, "legality_analyst");
	const inspector = screen.getByRole("region", {
		name: "legality_analyst inspector",
	});
	fireEvent.click(within(inspector).getByRole("tab", { name: "Context" }));
	expect(
		within(inspector).getByText("Configuration was not recorded for this run."),
	).toBeDefined();
	fireEvent.click(within(inspector).getByRole("tab", { name: "Thinking" }));
	expect(within(inspector).getByText(/No thinking was recorded/)).toBeDefined();
});
it("moves selection with arrow keys and keeps the Log view", () => {
	const { onSelect } = mount(steps, "supervisor");
	const first = within(tree()).getByRole("treeitem", {
		name: label("supervisor"),
	});
	expect(first.getAttribute("aria-selected")).toBe("true");
	first.focus();
	fireEvent.keyDown(first, { key: "ArrowDown" });
	expect(onSelect).toHaveBeenCalledWith("geospatial_analyst", undefined);
	fireEvent.click(screen.getByRole("button", { name: "Log" }));
	expect(screen.getByRole("list", { name: "Agent run steps" })).toBeDefined();
	expect(screen.getByText(/00:00:13.000 UTC/)).toBeDefined();
});
it("uses a Sheet inspector below xl", () => {
	vi.mocked(window.matchMedia).mockImplementation((query) => ({
		matches: false,
		media: query,
		onchange: null,
		addListener: () => {},
		removeListener: () => {},
		addEventListener: () => {},
		removeEventListener: () => {},
		dispatchEvent: () => true,
	}));
	mount();
	fireEvent.click(
		within(tree()).getByRole("treeitem", { name: label("legality_analyst") }),
	);
	expect(screen.getByRole("dialog")).toBeDefined();
	expect(screen.getByText("Agent inspector")).toBeDefined();
});
it("shows an in-flight tool as running, then its dataset card when it returns", () => {
	const started = [
		steps[1] as TraceStep,
		step(2, "agent", "geospatial_analyst", "delegated", {
			agent: "geospatial_analyst",
			invocation: 1,
			event: "start",
			input: "Screen PLY-001",
		}),
		step(3, "tool", "get_tree_cover_loss", "called", {
			agent: "geospatial_analyst",
			invocation: 1,
			event: "tool_start",
			tool_use_id: "t1",
			input: { polygon_id: "PLY-001" },
		}),
	];
	const { unmount } = mount(started, undefined, undefined, "running");
	// Nothing selected: the inspector follows the specialist doing the work.
	const inspector = screen.getByRole("region", {
		name: "geospatial_analyst inspector",
	});
	expect(
		within(inspector).getByText(/calling get_tree_cover_loss/),
	).toBeDefined();
	const datasets = screen.getByRole("list", { name: "Checked against" });
	expect(within(datasets).getByText("In progress")).toBeDefined();
	unmount();
	mount(
		[
			...started,
			step(4, "tool", "get_tree_cover_loss", "PLY-001: 1.08 ha", {
				agent: "geospatial_analyst",
				invocation: 1,
				event: "tool_end",
				tool_use_id: "t1",
				status: "ok",
				duration_ms: 900,
				result: {
					dataset: "umd_tree_cover_loss",
					version: "v1.13",
					date_window: "2021-2025",
					total_loss_ha: 1.07698,
					cached: false,
					by_year: [{ year: 2023, loss_ha: 0.46 }],
				},
			}),
		],
		undefined,
		undefined,
		"running",
	);
	const card = within(screen.getByRole("list", { name: "Checked against" }));
	expect(card.getByText("1.08 ha lost")).toBeDefined();
	expect(card.getByText(/umd_tree_cover_loss v1.13 · 2021-2025/)).toBeDefined();
	expect(card.getByText("live")).toBeDefined();
});
it("opens a failed verifier with its challenges when nothing is selected", () => {
	mount(
		[
			step(1, "verifier", "verifier", "started", {
				agent: "verifier",
				invocation: 1,
				event: "start",
			}),
			step(2, "verifier", "verification", "rejected: 1 challenge(s)", {
				agent: "verifier",
				invocation: 1,
				event: "finish",
				accepted: false,
				challenges: [
					{
						kind: "missing_source",
						severity: "error",
						detail: "data_gaps is empty",
					},
				],
			}),
			step(3, "state", "failed"),
		],
		undefined,
		undefined,
		"failed",
	);
	const inspector = screen.getByRole("region", { name: "verifier inspector" });
	expect(
		within(inspector).getByText("1 verification challenge(s)"),
	).toBeDefined();
	expect(within(inspector).getByText("data_gaps is empty")).toBeDefined();
});

import type { TraceStep } from "@terrasentry/api-client";
import { DateTime } from "effect";
import { expect, it } from "vitest";
import { deriveAgentRun, focusAgent, groupTools } from "./agent-run";

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
const config = step(0, "run", "configuration", "", {
	task: "Assess REC-001",
	models: { orchestrator: "model-a", extraction: "model-b" },
	params: { orchestrator: { temperature: 0.2 } },
	agents: [
		{
			name: "supervisor",
			role: "orchestrator",
			model: "model-a",
			tools: ["thermal_analyst"],
			system_prompt: "Supervise",
		},
		{
			name: "thermal_analyst",
			role: "extraction",
			model: "model-b",
			tools: ["get_fire_hotspots"],
			system_prompt: "Inspect fire",
		},
		{
			name: "verifier",
			role: "orchestrator",
			model: "model-a",
			tools: [],
			system_prompt: "Verify",
		},
	],
});
it("groups historical tools and two retasks without new payload fields", () => {
	const run = deriveAgentRun(
		[
			step(1, "agent", "supervisor", "started"),
			step(2, "agent", "geospatial_analyst"),
			step(3, "tool", "get_tree_cover_loss"),
			step(4, "agent", "thermal_analyst"),
			step(5, "tool", "get_fire_hotspots"),
			step(6, "agent", "legality_analyst"),
			step(7, "tool", "get_legality_record"),
			step(8, "retask", "legality_analyst", "check concessions", {
				ordinal: 2,
				reason: "check concessions",
			}),
			step(9, "tool", "check_concession_overlap"),
			step(10, "retask", "geospatial_analyst", "get layers", {
				ordinal: 2,
				reason: "get layers",
			}),
			step(11, "tool", "get_context_layers"),
			step(12, "agent", "supervisor", "finished"),
		],
		{ model: "sap", state: "complete" },
	);
	expect(run.totals.agentCount).toBe(4);
	expect(run.config.recorded).toBe(false);
	expect(run.config.models.orchestrator).toBe("sap");
	expect(
		run.agents.find((a) => a.name === "geospatial_analyst")?.invocations[1]
			?.tools[0]?.step.name,
	).toBe("get_context_layers");
	expect(
		run.agents.find((a) => a.name === "legality_analyst")?.invocations[1]
			?.input,
	).toBe("check concessions");
});
it("uses explicit attribution and sums usage per invocation", () => {
	const run = deriveAgentRun(
		[
			config,
			step(1, "agent", "thermal_analyst", "delegated", {
				agent: "thermal_analyst",
				invocation: 1,
				input: "Inspect PLY-001",
			}),
			step(2, "tool", "custom_tool", "", {
				agent: "thermal_analyst",
				invocation: 1,
				input: { polygon_id: "PLY-001" },
				result: { count: 2 },
				duration_ms: 250,
				started_at: DateTime.formatIso(DateTime.makeUnsafe(base + 1750)),
			}),
			step(3, "report", "thermal_analyst", "reported", {
				agent: "thermal_analyst",
				invocation: 1,
				report: "Found fire",
				usage: { inputTokens: 10, outputTokens: 5, totalTokens: 15 },
			}),
			step(4, "retask", "thermal_analyst", "again", {
				agent: "thermal_analyst",
				invocation: 2,
				input: "Again",
			}),
			step(5, "report", "thermal_analyst", "reported", {
				agent: "thermal_analyst",
				invocation: 2,
				usage: { inputTokens: 7, outputTokens: 3, totalTokens: 10 },
			}),
		],
		{ model: "sap", state: "complete" },
	);
	const agent = run.agents.find((a) => a.name === "thermal_analyst");
	expect(agent?.tokens).toBe(25);
	expect(run.totals.tokens).toBe(25);
	expect(run.totals.toolCount).toBe(1);
	expect(agent?.invocations[0]?.tools[0]?.start).toBe(base + 1750);
	expect(agent?.model).toBe("model-b");
});
it("keeps live thermal running, verifier pending and investigation active", () => {
	const run = deriveAgentRun(
		[
			config,
			step(1, "agent", "supervisor", "started"),
			step(2, "agent", "thermal_analyst"),
			step(3, "tool", "get_fire_hotspots"),
		],
		{ model: "scripted", state: "running", now: base + 4500 },
	);
	expect(run.agents.find((a) => a.name === "thermal_analyst")?.status).toBe(
		"running",
	);
	expect(run.agents.find((a) => a.name === "verifier")?.status).toBe("pending");
	expect(run.stages[1]?.status).toBe("running");
	expect(run.totals.wallTimeMs).toBe(4500);
});
it("fails active agents and skips later stages", () => {
	const run = deriveAgentRun(
		[config, step(1, "agent", "thermal_analyst"), step(2, "state", "failed")],
		{ model: "sap", state: "failed" },
	);
	expect(run.agents.find((a) => a.name === "thermal_analyst")?.status).toBe(
		"failed",
	);
	expect(run.agents.find((a) => a.name === "verifier")?.status).toBe("skipped");
	expect(run.stages.slice(2).every((s) => s.status === "skipped")).toBe(true);
});
it("holds Decision for a person until review", () => {
	const steps = [
		step(1, "writer", "dds_writer"),
		step(2, "state", "awaiting_review"),
	];
	const run = deriveAgentRun(steps, { model: "sap", state: "awaiting_review" });
	expect(run.stages[5]?.status).toBe("running");
	expect(run.stages[5]?.label).toContain("waiting for a person");
	expect(
		deriveAgentRun([...steps, step(3, "review", "approve")], {
			model: "sap",
			state: "complete",
		}).stages[5]?.status,
	).toBe("done");
});
it("handles empty and malformed payloads", () => {
	const run = deriveAgentRun([], { model: "sap", state: "queued" });
	expect(run.agents).toEqual([]);
	expect(run.stages.every((s) => s.status === "pending")).toBe(true);
	expect(
		deriveAgentRun([step(1, "agent", "supervisor", "started", { agent: 42 })], {
			model: "sap",
			state: "running",
		}).agents[0]?.name,
	).toBe("supervisor");
});
it("shows retasked until completion and preserves verifier failure and usage", () => {
	expect(
		deriveAgentRun(
			[
				step(1, "agent", "geospatial_analyst"),
				step(2, "retask", "geospatial_analyst", "again", { ordinal: 2 }),
			],
			{ model: "sap", state: "running" },
		).agents[0]?.status,
	).toBe("retasked");
	const run = deriveAgentRun(
		[
			step(1, "verifier", "verifier", "started"),
			step(2, "verifier", "verification", "rejected", {
				agent: "verifier",
				accepted: false,
				usage: { inputTokens: 3, outputTokens: 2, totalTokens: 5 },
			}),
			step(3, "verifier", "verifier", "finished", { agent: "verifier" }),
		],
		{ model: "sap", state: "failed" },
	);
	expect(run.agents[0]?.status).toBe("failed");
	expect(run.totals.tokens).toBe(5);
});

it("does not turn a thought named after a tool into a tool call", () => {
	const run = deriveAgentRun(
		[
			step(1, "thought", "check_concession_overlap", "", {
				agent: "legality_analyst",
				text: "Model-written claim",
			}),
		],
		{ model: "sap", state: "running" },
	);
	expect(run.totals.toolCount).toBe(0);
	expect(run.agents[0]?.invocations[0]?.thoughts).toHaveLength(1);
});

it("keeps the verifier input and result through its graph finish", () => {
	const run = deriveAgentRun(
		[
			step(1, "verifier", "verifier", "started", {
				agent: "verifier",
				invocation: 1,
			}),
			step(2, "verifier", "verifier", "invoked", {
				agent: "verifier",
				invocation: 1,
				input: "Verify the observed claims",
			}),
			step(3, "verifier", "verification", "accepted: 0 challenges", {
				agent: "verifier",
				invocation: 1,
				accepted: true,
			}),
			step(4, "verifier", "verifier", "finished", {
				agent: "verifier",
				invocation: 1,
			}),
		],
		{ model: "sap", state: "complete" },
	);
	expect(run.agents[0]?.invocations[0]?.input).toBe(
		"Verify the observed claims",
	);
	expect(run.agents[0]?.invocations[0]?.report).toBe("accepted: 0 challenges");
});

it("pairs tool_start and tool_end by tool_use_id and keeps unfinished calls running", () => {
	const call = (index: number, event: string, id: string, extra = {}) =>
		step(index, "verifier", "get_evidence_entry", "", {
			agent: "verifier",
			invocation: 1,
			event,
			tool_use_id: id,
			...extra,
		});
	const live = deriveAgentRun(
		[
			step(0, "verifier", "verifier", "started", {
				agent: "verifier",
				event: "start",
			}),
			call(1, "tool_start", "a"),
			call(2, "tool_start", "b"),
			call(3, "tool_end", "a", { status: "ok", duration_ms: 5 }),
		],
		{ model: "sap", state: "running", now: base + 4000 },
	);
	const tools = live.agents[0]?.invocations[0]?.tools ?? [];
	expect(tools.map((tool) => tool.status)).toEqual(["ok", "running"]);
	expect(tools[0]?.start).toBe(base + 1000);
	expect(live.totals.toolCount).toBe(2);
	// Repeated lookups collapse into one row with every call kept.
	const [group] = groupTools(live.agents[0]?.invocations[0] as never);
	expect(group?.calls).toHaveLength(2);
	expect(group?.status).toBe("running");
	// A run that ended with the call still open marks it as an error, not "running".
	const ended = deriveAgentRun(
		[call(1, "tool_start", "a"), step(2, "state", "failed")],
		{ model: "sap", state: "failed" },
	);
	expect(ended.agents[0]?.invocations[0]?.tools[0]?.status).toBe("error");
});
it("focuses the working specialist rather than the supervisor, and records delegations", () => {
	const run = deriveAgentRun(
		[
			step(1, "agent", "supervisor", "started", {
				agent: "supervisor",
				event: "start",
			}),
			step(2, "agent", "thermal_analyst", "delegated", {
				agent: "thermal_analyst",
				event: "start",
			}),
		],
		{ model: "sap", state: "running", now: base + 3000 },
	);
	expect(focusAgent(run)?.name).toBe("thermal_analyst");
	expect(
		run.agents.find((a) => a.name === "supervisor")?.invocations[0]
			?.delegations,
	).toEqual([{ agent: "thermal_analyst", ordinal: 1, at: base + 2000 }]);
});

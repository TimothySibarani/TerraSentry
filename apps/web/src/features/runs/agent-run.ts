import type { TraceStep } from "@terrasentry/api-client";
import { DateTime, Option, Schema } from "effect";

const AgentConfig = Schema.Struct({
	name: Schema.String,
	role: Schema.Literals(["orchestrator", "extraction", "code"]),
	model: Schema.optionalKey(Schema.String),
	tools: Schema.optionalKey(Schema.Array(Schema.String)),
	system_prompt: Schema.optionalKey(Schema.NullOr(Schema.String)),
});
const RecordContext = Schema.Struct({
	record_id: Schema.optionalKey(Schema.String),
	supplier_id: Schema.optionalKey(Schema.String),
	polygon_id: Schema.optionalKey(Schema.String),
	region: Schema.optionalKey(Schema.String),
	area_ha: Schema.optionalKey(Schema.Number),
	commodity: Schema.optionalKey(Schema.String),
	hs_heading: Schema.optionalKey(Schema.String),
});
const Configuration = Schema.Struct({
	task: Schema.String,
	models: Schema.Record(Schema.String, Schema.String),
	params: Schema.Record(
		Schema.String,
		Schema.Record(Schema.String, Schema.Unknown),
	),
	agents: Schema.Array(AgentConfig),
	record: Schema.optionalKey(RecordContext),
});
const Usage = Schema.Struct({
	inputTokens: Schema.Number,
	outputTokens: Schema.Number,
	totalTokens: Schema.Number,
});
const Challenge = Schema.Struct({
	kind: Schema.String,
	severity: Schema.String,
	detail: Schema.String,
});
const Payload = Schema.Struct({
	event: Schema.optionalKey(
		Schema.Literals(["start", "finish", "tool_start", "tool_end", "thought"]),
	),
	agent: Schema.optionalKey(Schema.String),
	invocation: Schema.optionalKey(Schema.Number),
	ordinal: Schema.optionalKey(Schema.Number),
	tool_use_id: Schema.optionalKey(Schema.NullOr(Schema.String)),
	input: Schema.optionalKey(Schema.Unknown),
	result: Schema.optionalKey(Schema.Unknown),
	reason: Schema.optionalKey(Schema.String),
	report: Schema.optionalKey(Schema.String),
	reasoning: Schema.optionalKey(Schema.String),
	text: Schema.optionalKey(Schema.String),
	started_at: Schema.optionalKey(Schema.String),
	duration_ms: Schema.optionalKey(Schema.Number),
	status: Schema.optionalKey(Schema.String),
	usage: Schema.optionalKey(Usage),
	failed: Schema.optionalKey(Schema.Boolean),
	truncated: Schema.optionalKey(Schema.Boolean),
	accepted: Schema.optionalKey(Schema.Boolean),
	challenges: Schema.optionalKey(Schema.Array(Challenge)),
});
export type TracePayload = typeof Payload.Type;
export type VerificationChallenge = typeof Challenge.Type;
export type RunRecordContext = typeof RecordContext.Type;
export const tracePayload = (step: TraceStep): TracePayload =>
	Option.getOrElse(
		Schema.decodeUnknownOption(Payload)(step.payload),
		() => ({}),
	);
export type AgentStatus =
	| "pending"
	| "running"
	| "done"
	| "failed"
	| "retasked"
	| "skipped";
export type StageStatus = Exclude<AgentStatus, "retasked">;
export interface AgentToolCall {
	step: TraceStep;
	start: number;
	/** Undefined while the call is in flight (a `tool_start` without its `tool_end`). */
	end?: number;
	durationMs: number;
	input: unknown;
	result: unknown;
	status: "running" | "ok" | "error" | "recorded";
}
export interface AgentInvocation {
	ordinal: number;
	start: number;
	end?: number;
	input: unknown;
	thoughts: TraceStep[];
	tools: AgentToolCall[];
	/** Specialists this invocation delegated to (supervisor only). */
	delegations: { agent: string; ordinal: number; at: number }[];
	report: string;
	usage?: typeof Usage.Type;
	challenges: VerificationChallenge[];
	failed: boolean;
}
export interface RunAgent {
	name: string;
	role: "orchestrator" | "extraction" | "code";
	model: string;
	tools: readonly string[];
	systemPrompt: string | null;
	status: AgentStatus;
	invocations: AgentInvocation[];
	tokens: number;
	durationMs: number;
}
export interface PipelineStage {
	name: string;
	status: StageStatus;
	label: string;
}
/** Consecutive calls to one tool within an invocation, shown as one timeline row. */
export interface ToolGroup {
	key: string;
	name: string;
	ordinal: number;
	calls: AgentToolCall[];
	start: number;
	end?: number;
	status: AgentToolCall["status"];
}

// Mirrors build_specialists / build_verifier_tools in Python; only for traces without attribution.
const TOOL_AGENT: Record<string, string> = {
	get_tree_cover_loss: "geospatial_analyst",
	get_context_layers: "geospatial_analyst",
	get_fire_hotspots: "thermal_analyst",
	get_legality_record: "legality_analyst",
	get_consignment: "legality_analyst",
	check_concession_overlap: "legality_analyst",
	search_adverse_media: "legality_analyst",
	get_source_claims: "verifier",
	get_assessment: "verifier",
	list_evidence_claims: "verifier",
	get_evidence_entry: "verifier",
};
const AGENT_ORDER = [
	"supervisor",
	"geospatial_analyst",
	"thermal_analyst",
	"legality_analyst",
	"assessor",
	"verifier",
	"dds_writer",
];
const CODE_NODES = new Set(["assessor", "dds_writer"]);
export const stepTime = (step: TraceStep) => DateTime.toEpochMillis(step.at);
const isoMillis = (value: string | undefined) =>
	value === undefined
		? Option.none<number>()
		: Option.map(DateTime.make(value), DateTime.toEpochMillis);

/** The event a step stands for. New traces say it explicitly; old ones are inferred once, here. */
function eventOf(step: TraceStep, payload: TracePayload, name: string) {
	if (payload.event) return payload.event;
	if (step.kind === "thought") return "thought";
	if (step.kind === "tool" || TOOL_AGENT[step.name] !== undefined)
		return "tool_end";
	if (step.kind === "retask") return "start";
	if (step.kind === "report" || step.detail === "finished") return "finish";
	if (step.name === "verification") return "finish";
	if (CODE_NODES.has(name)) return "finish";
	if (step.kind === "agent" || step.kind === "verifier") return "start";
	return undefined;
}

/** Facts in trace payloads are decoded here; renderers consume only this view model. */
export function deriveAgentRun(
	steps: readonly TraceStep[],
	options: {
		model: string;
		state: string;
		now?: number;
		verification?: { challenges?: readonly unknown[] } | null;
	},
) {
	const ordered = [...steps].sort((a, b) => stepTime(a) - stepTime(b));
	const configuration = ordered.find(
		(step) => step.name === "configuration" && step.kind === "run",
	);
	const recordedConfig = configuration
		? Option.getOrUndefined(
				Schema.decodeUnknownOption(Configuration)(configuration.payload),
			)
		: undefined;
	const config = {
		recorded: recordedConfig !== undefined,
		task: recordedConfig?.task ?? "",
		models: recordedConfig?.models ?? {
			orchestrator: options.model,
			extraction: options.model,
		},
		params: recordedConfig?.params ?? {},
		agents: recordedConfig?.agents ?? [],
		record: recordedConfig?.record ?? {},
	};
	const start = ordered[0] ? stepTime(ordered[0]) : 0;
	const last = ordered.at(-1);
	const inFlight = ["queued", "running", "needs_more_data"].includes(
		options.state,
	);
	const end = Math.max(
		start,
		last ? stepTime(last) : start,
		inFlight ? (options.now ?? start) : start,
	);
	const byName = new Map<string, RunAgent>();
	function getAgent(name: string): RunAgent {
		const existing = byName.get(name);
		if (existing) return existing;
		const declared = config.agents.find((agent) => agent.name === name);
		const role =
			declared?.role ??
			(CODE_NODES.has(name)
				? "code"
				: name.endsWith("_analyst")
					? "extraction"
					: "orchestrator");
		const agent: RunAgent = {
			name,
			role,
			model:
				declared?.model ??
				(role === "code" ? "code" : (config.models[role] ?? options.model)),
			tools:
				declared?.tools ??
				Object.keys(TOOL_AGENT).filter((tool) => TOOL_AGENT[tool] === name),
			systemPrompt: declared?.system_prompt ?? null,
			status: "pending",
			invocations: [],
			tokens: 0,
			durationMs: 0,
		};
		byName.set(name, agent);
		return agent;
	}
	for (const agent of config.agents) getAgent(agent.name);
	const supervisorAt = (at: number) =>
		byName
			.get("supervisor")
			?.invocations.find(
				(item) => item.start <= at && (item.end ?? Infinity) >= at,
			);
	for (const step of ordered) {
		if (step.name === "configuration" || step.kind === "state") continue;
		const payload = tracePayload(step);
		const name =
			payload.agent ??
			TOOL_AGENT[step.name] ??
			(step.name === "verification" ? "verifier" : step.name);
		if (step.kind === "review" || step.kind === "sap") continue;
		const event = eventOf(step, payload, name);
		if (!event) continue;
		const at = stepTime(step);
		const agent = getAgent(name);
		const ordinal =
			payload.invocation ??
			payload.ordinal ??
			(step.kind === "retask"
				? agent.invocations.length + 1
				: (agent.invocations.at(-1)?.ordinal ?? 1));
		let invocation = agent.invocations.find((item) => item.ordinal === ordinal);
		if (!invocation) {
			const previous = agent.invocations.at(-1);
			if (previous && previous.end === undefined) previous.end = at;
			invocation = {
				ordinal,
				start: at,
				input:
					payload.input ??
					payload.reason ??
					(name === "supervisor" ? config.task : ""),
				thoughts: [],
				tools: [],
				delegations: [],
				report: "",
				challenges: [],
				failed: false,
			};
			agent.invocations.push(invocation);
			if (agent.role === "extraction")
				supervisorAt(at)?.delegations.push({ agent: name, ordinal, at });
		} else if (event === "start" && payload.input !== undefined)
			invocation.input = payload.input;
		if (event === "thought") invocation.thoughts.push(step);
		if (event === "tool_start") {
			invocation.tools.push({
				step,
				start: at,
				durationMs: 0,
				input: payload.input,
				result: undefined,
				status: "running",
			});
		}
		if (event === "tool_end") {
			const durationMs = Math.max(0, payload.duration_ms ?? 0);
			const toolStart = Math.min(
				at,
				Option.getOrElse(isoMillis(payload.started_at), () => at - durationMs),
			);
			const status =
				payload.status === "error"
					? "error"
					: payload.status === "ok"
						? "ok"
						: "recorded";
			const pending = payload.tool_use_id
				? invocation.tools.find(
						(tool) =>
							tool.status === "running" &&
							tracePayload(tool.step).tool_use_id === payload.tool_use_id,
					)
				: undefined;
			const call: AgentToolCall = {
				step,
				start: pending ? Math.min(pending.start, toolStart) : toolStart,
				end: at,
				durationMs,
				input: payload.input,
				result: payload.result,
				status,
			};
			if (pending)
				invocation.tools.splice(invocation.tools.indexOf(pending), 1, call);
			else invocation.tools.push(call);
			invocation.start = Math.min(invocation.start, call.start);
		}
		if (event === "finish") {
			invocation.end = at;
			invocation.report = payload.report ?? (invocation.report || step.detail);
			invocation.usage = payload.usage ?? invocation.usage;
			if (payload.challenges) invocation.challenges = [...payload.challenges];
			invocation.failed ||=
				payload.failed === true || payload.accepted === false;
		}
		// Old runs did not guarantee specialist finishes. Supervisor completion closes their spans.
		if (name === "supervisor" && event === "finish") {
			for (const other of byName.values())
				if (other.role === "extraction") {
					const active = other.invocations.at(-1);
					if (active && active.end === undefined) active.end = at;
				}
		}
	}
	for (const agent of byName.values()) {
		const latest = agent.invocations.at(-1);
		if (!latest) agent.status = inFlight ? "pending" : "skipped";
		else {
			if (!inFlight && latest.end === undefined) {
				latest.end = end;
				latest.failed = options.state === "failed";
			}
			if (!inFlight)
				for (const item of agent.invocations)
					for (const tool of item.tools)
						if (tool.end === undefined) {
							tool.end = item.end ?? end;
							tool.status = "error";
						}
			agent.status = latest.failed
				? "failed"
				: latest.end !== undefined
					? "done"
					: latest.ordinal > 1
						? "retasked"
						: "running";
		}
		agent.tokens = agent.invocations.reduce(
			(sum, item) => sum + (item.usage?.totalTokens ?? 0),
			0,
		);
		agent.durationMs = agent.invocations.reduce(
			(sum, item) => sum + Math.max(0, (item.end ?? end) - item.start),
			0,
		);
	}
	if (options.verification?.challenges?.length) {
		const verifier = byName.get("verifier");
		const invocation = verifier?.invocations.at(-1);
		if (
			invocation &&
			invocation.end !== undefined &&
			invocation.challenges.length === 0
		) {
			invocation.challenges = options.verification.challenges
				.map((c) =>
					Option.getOrUndefined(Schema.decodeUnknownOption(Challenge)(c)),
				)
				.filter((c): c is VerificationChallenge => c !== undefined);
		}
	}
	const agents = [...byName.values()].sort(
		(a, b) => AGENT_ORDER.indexOf(a.name) - AGENT_ORDER.indexOf(b.name),
	);
	const stages: PipelineStage[] = [
		"Queued",
		"Investigating",
		"Assessing",
		"Verifying",
		"Writing DDS",
		"Decision",
	].map((name) => ({ name, status: "pending", label: name }));
	if (ordered.length) {
		const has = (name: string) => ordered.some((step) => step.name === name);
		const phase = has("dds_writer")
			? 4
			: has("verifier") || has("verification")
				? 3
				: has("assessor")
					? 2
					: has("supervisor") ||
							agents.some((agent) => agent.invocations.length)
						? 1
						: 0;
		for (let i = 0; i < phase; i++) {
			const stage = stages[i];
			if (stage) stage.status = "done";
		}
		const current = stages[phase];
		if (current)
			current.status = options.state === "failed" ? "failed" : "running";
		if (options.state === "failed") {
			for (const stage of stages.slice(phase + 1)) stage.status = "skipped";
		} else if (
			options.state === "complete" ||
			options.state === "awaiting_review" ||
			ordered.some((step) => step.kind === "review")
		) {
			for (const stage of stages) stage.status = "done";
			const decision = stages[5];
			if (
				decision &&
				options.state === "awaiting_review" &&
				!ordered.some((step) => step.kind === "review")
			) {
				decision.status = "running";
				decision.label = "Decision · waiting for a person";
			}
		}
	}
	return {
		config,
		stages,
		agents,
		start,
		end,
		totals: {
			agentCount: agents.filter(
				(agent) => agent.role !== "code" && agent.invocations.length > 0,
			).length,
			activeCount: agents.filter(
				(agent) => agent.status === "running" || agent.status === "retasked",
			).length,
			toolCount: agents.reduce(
				(sum, agent) =>
					sum + agent.invocations.reduce((n, item) => n + item.tools.length, 0),
				0,
			),
			tokens: agents.reduce((sum, agent) => sum + agent.tokens, 0),
			wallTimeMs: end - start,
		},
	};
}
export type AgentRun = ReturnType<typeof deriveAgentRun>;

/** Collapse back-to-back calls of the same tool (the verifier's 34 evidence lookups) into one row. */
export function groupTools(invocation: AgentInvocation): ToolGroup[] {
	const groups: ToolGroup[] = [];
	for (const call of [...invocation.tools].sort((a, b) => a.start - b.start)) {
		const previous = groups.at(-1);
		if (previous && previous.name === call.step.name) {
			previous.calls.push(call);
			previous.end =
				previous.end === undefined || call.end === undefined
					? undefined
					: Math.max(previous.end, call.end);
			if (call.status === "running" || call.status === "error")
				previous.status = call.status;
			continue;
		}
		groups.push({
			key: call.step.step_id,
			name: call.step.name,
			ordinal: invocation.ordinal,
			calls: [call],
			start: call.start,
			end: call.end,
			status: call.status,
		});
	}
	return groups;
}

/** Which agent a reviewer should look at first for this run state. */
export function focusAgent(run: AgentRun): RunAgent | undefined {
	const live = run.agents.filter(
		(agent) => agent.status === "running" || agent.status === "retasked",
	);
	// The supervisor is "running" for the whole investigation; the specialist doing the work is more useful.
	return (
		live.find((agent) => agent.name !== "supervisor") ??
		live[0] ??
		run.agents.find((agent) => agent.status === "failed") ??
		run.agents.find(
			(agent) => agent.name === "verifier" && agent.invocations.length,
		) ??
		run.agents.find((agent) => agent.invocations.length) ??
		run.agents[0]
	);
}

export function findToolCall(run: AgentRun, stepId: string | undefined) {
	if (!stepId) return undefined;
	for (const agent of run.agents)
		for (const invocation of agent.invocations)
			for (const call of invocation.tools)
				if (call.step.step_id === stepId) return { agent, invocation, call };
	return undefined;
}

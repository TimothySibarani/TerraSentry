import { Option, Schema } from "effect";
import type { AgentRun, AgentToolCall } from "./agent-run";

const n = Schema.optionalKey(Schema.NullOr(Schema.Number));
const s = Schema.optionalKey(Schema.NullOr(Schema.String));
const b = Schema.optionalKey(Schema.NullOr(Schema.Boolean));
const Layer = Schema.Struct({
	name: Schema.String,
	dataset: s,
	version: s,
	status: s,
	error: s,
	overlap_ha: n,
	feature_count: n,
	fetched_at: s,
	cached: b,
});
export const LossResult = Schema.Struct({
	dataset: s,
	version: s,
	date_window: s,
	total_loss_ha: n,
	cached: b,
	error: s,
	by_year: Schema.optionalKey(
		Schema.Array(
			Schema.Struct({ year: Schema.Number, loss_ha: Schema.Number }),
		),
	),
	context_summary: Schema.optionalKey(Schema.Array(Layer)),
});
export const HotspotResult = Schema.Struct({
	source: s,
	date_window: s,
	detection_count: n,
	total_frp: n,
	last_detection: s,
	cached: b,
	error: s,
});
export const LayersResult = Schema.Struct({
	layers: Schema.Array(Layer),
	error: s,
});
export const LegalityResult = Schema.Struct({
	legal_name: s,
	permit_status: s,
	permit_expiry: s,
	hgu_number: s,
	pbp_number: s,
	declared_holder: s,
	provenance: s,
	synthetic: b,
	certifications: Schema.optionalKey(Schema.Array(Schema.String)),
	sanctions: Schema.optionalKey(Schema.Array(Schema.Unknown)),
});
export const ConsignmentResult = Schema.Struct({
	commodity: s,
	description: s,
	hs_heading: s,
	net_weight_kg: n,
	synthetic: b,
});
export const ConcessionResult = Schema.Struct({
	overlap_found: b,
	declared_holder: s,
	concessions: Schema.optionalKey(Schema.Array(Schema.Unknown)),
	unavailable_layers: Schema.optionalKey(Schema.Array(Schema.String)),
	error: s,
});
export const decode = <S extends Schema.ConstraintDecoder<unknown>>(
	schema: S,
	value: unknown,
): S["Type"] | undefined =>
	Option.getOrUndefined(Schema.decodeUnknownOption(schema)(value));

export interface DatasetCard {
	key: string;
	title: string;
	source: string;
	window?: string;
	metric: string;
	status: "running" | "ok" | "error" | "truncated";
	/** True when the value came from the cache rather than a live fetch. */
	cached?: boolean;
	fetchedAt?: string;
	agent: string;
	stepId: string;
	synthetic?: boolean;
}

const ha = (value: number | null | undefined) =>
	value === null || value === undefined
		? "—"
		: `${value.toLocaleString("en-GB", { maximumFractionDigits: 2 })} ha`;

const LAYER_TITLE: Record<string, string> = {
	protected_areas: "Protected areas",
	moratorium: "Forest moratorium",
	peat: "Peatland",
	oil_palm_concessions: "Oil palm concessions",
	wood_fiber_concessions: "Wood fibre concessions",
	logging_concessions: "Logging concessions",
};
export const layerTitle = (name: string) =>
	LAYER_TITLE[name] ?? name.replaceAll("_", " ");

function layerCards(
	layers: ReadonlyArray<typeof Layer.Type>,
	call: AgentToolCall,
	agent: string,
): DatasetCard[] {
	return layers.map((layer) => ({
		key: `layer:${layer.name}`,
		title: layerTitle(layer.name),
		source:
			[layer.dataset, layer.version].filter(Boolean).join(" ") ||
			"Context layer",
		metric:
			layer.status && layer.status !== "success"
				? (layer.error ?? layer.status)
				: `${ha(layer.overlap_ha)} overlap · ${layer.feature_count ?? 0} feature(s)`,
		status: layer.status && layer.status !== "success" ? "error" : "ok",
		cached: layer.cached ?? undefined,
		fetchedAt: layer.fetched_at ?? undefined,
		agent,
		stepId: call.step.step_id,
	}));
}

const PENDING_TITLE: Record<string, string> = {
	get_tree_cover_loss: "Tree cover loss",
	get_fire_hotspots: "Fire hotspots",
	get_context_layers: "Context layers",
	get_legality_record: "Declared legality",
	get_consignment: "Consignment",
	check_concession_overlap: "Concession overlap",
};

/** The datasets the agents actually read, built from recorded tool results (never from model text). */
export function datasetCards(run: AgentRun): DatasetCard[] {
	const cards = new Map<string, DatasetCard>();
	const calls = run.agents
		.filter((agent) => agent.role === "extraction")
		.flatMap((agent) =>
			agent.invocations.flatMap((invocation) =>
				invocation.tools.map((call) => ({ agent: agent.name, call })),
			),
		)
		.sort((a, b) => a.call.start - b.call.start);
	for (const { agent, call } of calls) {
		const name = call.step.name;
		const base = { agent, stepId: call.step.step_id };
		const title = PENDING_TITLE[name];
		if (!title) continue;
		if (call.status === "running") {
			if (!cards.has(name))
				cards.set(name, {
					...base,
					key: name,
					title,
					source: "Fetching…",
					metric: "In progress",
					status: "running",
				});
			continue;
		}
		const result = call.result;
		if (decode(Schema.Struct({ truncated: Schema.Literal(true) }), result)) {
			cards.set(name, {
				...base,
				key: name,
				title,
				source: "Result too large to keep",
				metric: "Open the tool call for the preview",
				status: "truncated",
			});
			continue;
		}
		const errored = call.status === "error";
		if (name === "get_tree_cover_loss") {
			const loss = decode(LossResult, result);
			if (!loss) continue;
			cards.set(name, {
				...base,
				key: name,
				title,
				source: `Hansen GFC ${loss.dataset ?? ""} ${loss.version ?? ""}`.trim(),
				window: loss.date_window ?? undefined,
				metric: errored
					? (loss.error ?? "unavailable")
					: `${ha(loss.total_loss_ha)} lost`,
				status: errored ? "error" : "ok",
				cached: loss.cached ?? undefined,
			});
			// Screening reads layer summaries with the loss call; a deep dive replaces them below.
			for (const card of layerCards(loss.context_summary ?? [], call, agent))
				if (!cards.has(card.key)) cards.set(card.key, card);
		} else if (name === "get_fire_hotspots") {
			const fire = decode(HotspotResult, result);
			if (!fire) continue;
			cards.set(name, {
				...base,
				key: name,
				title,
				source: `NASA FIRMS ${fire.source ?? ""}`.trim(),
				window: fire.date_window ?? undefined,
				metric: errored
					? (fire.error ?? "unavailable")
					: `${fire.detection_count ?? 0} detection(s)`,
				status: errored ? "error" : "ok",
				cached: fire.cached ?? undefined,
			});
		} else if (name === "get_context_layers") {
			const layers = decode(LayersResult, result);
			for (const card of layerCards(layers?.layers ?? [], call, agent))
				cards.set(card.key, card);
		} else if (name === "get_legality_record") {
			const legality = decode(LegalityResult, result);
			if (!legality) continue;
			cards.set(name, {
				...base,
				key: name,
				title,
				source: legality.legal_name ?? "Supplier record",
				metric: `Permit ${legality.permit_status ?? "unknown"}${legality.hgu_number ? ` · ${legality.hgu_number}` : ""}`,
				status: errored ? "error" : "ok",
				synthetic: legality.synthetic ?? undefined,
			});
		} else if (name === "get_consignment") {
			const consignment = decode(ConsignmentResult, result);
			if (!consignment) continue;
			cards.set(name, {
				...base,
				key: name,
				title,
				source:
					consignment.description ?? consignment.commodity ?? "Consignment",
				metric: `HS ${consignment.hs_heading ?? "—"}${consignment.net_weight_kg ? ` · ${(consignment.net_weight_kg / 1000).toLocaleString("en-GB", { maximumFractionDigits: 0 })} t` : ""}`,
				status: errored ? "error" : "ok",
				synthetic: consignment.synthetic ?? undefined,
			});
		} else if (name === "check_concession_overlap") {
			const overlap = decode(ConcessionResult, result);
			if (!overlap) continue;
			cards.set(name, {
				...base,
				key: name,
				title,
				source: overlap.declared_holder ?? "Concession layers",
				metric: errored
					? (overlap.error ?? "unavailable")
					: overlap.overlap_found
						? `${overlap.concessions?.length ?? 0} intersecting concession(s)`
						: "No intersecting concession",
				status: errored ? "error" : "ok",
			});
		}
	}
	return [...cards.values()];
}

import { Schema } from "effect";
import { Badge } from "#/components/ui/badge";
import { prettyJson } from "#/lib/format";
import {
	ConcessionResult,
	ConsignmentResult,
	decode,
	HotspotResult,
	LayersResult,
	LegalityResult,
	LossResult,
	layerTitle,
} from "./work-context";

export function JsonBlock({ value }: { value: unknown }) {
	return (
		<pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md bg-canvas-soft p-3 font-mono text-xs leading-relaxed">
			{value === undefined || value === ""
				? "Not recorded"
				: typeof value === "string"
					? value
					: prettyJson(value)}
		</pre>
	);
}

function Facts({
	rows,
}: {
	rows: [string, string | number | null | undefined][];
}) {
	return (
		<dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-body-sm">
			{rows
				.filter(
					([, value]) => value !== undefined && value !== null && value !== "",
				)
				.map(([label, value]) => (
					<div key={label} className="contents">
						<dt className="text-muted-foreground">{label}</dt>
						<dd className="min-w-0 break-words">{value}</dd>
					</div>
				))}
		</dl>
	);
}

const ha = (value: number | null | undefined) =>
	value === null || value === undefined
		? "—"
		: `${value.toLocaleString("en-GB", { maximumFractionDigits: 2 })} ha`;

/** A readable view of a source tool's result; falls back to JSON for anything unrecognised. */
export function ToolResultView({
	name,
	result,
}: {
	name: string;
	result: unknown;
}) {
	if (decode(Schema.Struct({ truncated: Schema.Literal(true) }), result))
		return <JsonBlock value={result} />;
	if (name === "get_tree_cover_loss") {
		const loss = decode(LossResult, result);
		if (loss) {
			const years = loss.by_year ?? [];
			const max = Math.max(0.0001, ...years.map((year) => year.loss_ha));
			return (
				<div className="flex flex-col gap-3">
					<Facts
						rows={[
							["Dataset", `${loss.dataset ?? ""} ${loss.version ?? ""}`.trim()],
							["Window", loss.date_window],
							["Total loss", ha(loss.total_loss_ha)],
							["Source", loss.cached ? "cache" : "live fetch"],
							["Error", loss.error],
						]}
					/>
					{years.length > 0 && (
						<table className="w-full text-body-sm">
							<caption className="sr-only">Tree cover loss by year</caption>
							<tbody>
								{years.map((year) => (
									<tr key={year.year}>
										<th
											scope="row"
											className="w-12 py-0.5 text-left font-normal tabular-nums text-muted-foreground"
										>
											{year.year}
										</th>
										<td className="py-0.5">
											<div
												className="h-2 rounded-sm bg-status-risk/60"
												style={{ width: `${(year.loss_ha / max) * 100}%` }}
											/>
										</td>
										<td className="w-20 py-0.5 text-right tabular-nums">
											{ha(year.loss_ha)}
										</td>
									</tr>
								))}
							</tbody>
						</table>
					)}
				</div>
			);
		}
	}
	if (name === "get_fire_hotspots") {
		const fire = decode(HotspotResult, result);
		if (fire)
			return (
				<Facts
					rows={[
						["Source", `NASA FIRMS ${fire.source ?? ""}`.trim()],
						["Window", fire.date_window],
						["Detections", fire.detection_count ?? 0],
						["Total FRP", fire.total_frp],
						["Last detection", fire.last_detection],
						["Fetched", fire.cached ? "cache" : "live fetch"],
						["Error", fire.error],
					]}
				/>
			);
	}
	if (name === "get_context_layers") {
		const layers = decode(LayersResult, result);
		if (layers)
			return (
				<table className="w-full text-body-sm">
					<caption className="sr-only">Context layers</caption>
					<thead className="text-left text-muted-foreground">
						<tr>
							<th scope="col" className="py-1 font-normal">
								Layer
							</th>
							<th scope="col" className="py-1 font-normal">
								Dataset
							</th>
							<th scope="col" className="py-1 text-right font-normal">
								Overlap
							</th>
						</tr>
					</thead>
					<tbody>
						{layers.layers.map((layer) => (
							<tr key={layer.name} className="border-t">
								<td className="py-1">{layerTitle(layer.name)}</td>
								<td className="py-1 font-mono text-xs text-muted-foreground">
									{layer.dataset} {layer.version}
								</td>
								<td className="py-1 text-right tabular-nums">
									{layer.status && layer.status !== "success" ? (
										<Badge variant="risk">{layer.status}</Badge>
									) : (
										ha(layer.overlap_ha)
									)}
								</td>
							</tr>
						))}
					</tbody>
				</table>
			);
	}
	if (name === "get_legality_record") {
		const legality = decode(LegalityResult, result);
		if (legality)
			return (
				<Facts
					rows={[
						["Legal name", legality.legal_name],
						["Declared holder", legality.declared_holder],
						["Permit", legality.permit_status],
						["Permit expiry", legality.permit_expiry ?? "not recorded"],
						["HGU", legality.hgu_number],
						["PBPH", legality.pbp_number],
						["Certifications", legality.certifications?.join(", ")],
						["Sanctions", legality.sanctions?.length ?? 0],
						[
							"Provenance",
							legality.synthetic ? "synthetic test data" : legality.provenance,
						],
					]}
				/>
			);
	}
	if (name === "get_consignment") {
		const consignment = decode(ConsignmentResult, result);
		if (consignment)
			return (
				<Facts
					rows={[
						["Commodity", consignment.commodity],
						["Description", consignment.description],
						["HS heading", consignment.hs_heading],
						[
							"Net weight",
							consignment.net_weight_kg
								? `${consignment.net_weight_kg.toLocaleString("en-GB")} kg`
								: undefined,
						],
						[
							"Provenance",
							consignment.synthetic ? "synthetic test data" : undefined,
						],
					]}
				/>
			);
	}
	if (name === "check_concession_overlap") {
		const overlap = decode(ConcessionResult, result);
		if (overlap)
			return (
				<Facts
					rows={[
						["Declared holder", overlap.declared_holder],
						["Overlap", overlap.overlap_found ? "yes" : "no"],
						["Concessions", overlap.concessions?.length ?? 0],
						[
							"Unavailable layers",
							overlap.unavailable_layers?.join(", ") || "none",
						],
						["Error", overlap.error],
					]}
				/>
			);
	}
	return <JsonBlock value={result} />;
}

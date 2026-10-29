import { useQuery } from "@tanstack/react-query";
import type {
	BatchRecord,
	OperatorRecord,
	RunOptions,
} from "@terrasentry/api-client";
import {
	BuildingIcon,
	ChevronDownIcon,
	LandmarkIcon,
	MapPinIcon,
	PackageIcon,
	SlidersHorizontalIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { type MapTone, MapView } from "#/components/map/map-view";
import { ProvenanceBadge } from "#/components/provenance-badge";
import { Button } from "#/components/ui/button";
import {
	Collapsible,
	CollapsibleContent,
	CollapsibleTrigger,
} from "#/components/ui/collapsible";
import { Skeleton } from "#/components/ui/skeleton";
import { decodeGeometry } from "#/features/runs/evidence";
import { runInputQuery } from "#/features/runs/queries";

type Row = [string, ReactNode | string | number | null | undefined];

const ha = (value: number | null | undefined) =>
	value === null || value === undefined
		? undefined
		: `${value.toLocaleString("en-GB", { maximumFractionDigits: 2 })} ha`;

const tonnes = (kg: number) =>
	`${(kg / 1000).toLocaleString("en-GB", { maximumFractionDigits: 0 })} t`;

const words = (value: string | null | undefined) =>
	value ? value.replaceAll("_", " ") : undefined;

const list = (values: ReadonlyArray<string>) =>
	values.length > 0 ? values.join(", ") : "None";

/** "high risk · legal" for a seeded record; `null` for a submitted (unlabelled) one. */
export function expectedLabel(record: BatchRecord): string | null {
	if (!record.expected_archetype) return null;
	const reason = record.expected_signal ?? record.expected_ambiguity;
	return [words(record.expected_archetype), words(reason)]
		.filter(Boolean)
		.join(" · ");
}

function Facts({ rows }: { rows: ReadonlyArray<Row> }) {
	return (
		<dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-body-sm">
			{rows
				.filter(
					([, value]) => value !== undefined && value !== null && value !== "",
				)
				.map(([label, value]) => (
					<div key={label} className="contents">
						<dt className="text-muted-foreground">{label}</dt>
						<dd className="min-w-0 break-words font-mono text-xs leading-5">
							{value}
						</dd>
					</div>
				))}
		</dl>
	);
}

function Section({
	title,
	icon: Icon,
	provenance,
	children,
}: {
	title: string;
	icon: typeof MapPinIcon;
	provenance?: string;
	children: ReactNode;
}) {
	return (
		<section
			aria-label={title}
			className="flex min-w-0 flex-col gap-2 rounded-lg border border-border bg-canvas-card p-3"
		>
			<header className="flex items-center justify-between gap-2">
				<h4 className="flex items-center gap-2 text-body-sm font-medium">
					<Icon aria-hidden="true" className="size-4 text-muted-foreground" />
					{title}
				</h4>
				{provenance && <ProvenanceBadge provenance={provenance} />}
			</header>
			{children}
		</section>
	);
}

/**
 * Exactly what a run is (or will be) given: the plot, the supplier's declared legality,
 * the consignment, the EU operator and the launch settings. Every section names its
 * provenance so synthetic seed data is never mistaken for an observation.
 */
export function RunInputPanel({
	record,
	operator,
	options,
	model,
	compact = false,
	tone = "neutral",
}: {
	record: BatchRecord;
	operator?: OperatorRecord | null;
	options?: RunOptions;
	model?: string;
	/** Drops the map, the operator and the settings: for scenario previews. */
	compact?: boolean;
	tone?: MapTone;
}) {
	const { polygon, legality, consignment } = record;
	const geometry = decodeGeometry(polygon.geometry);
	const permit = legality.hgu_number ?? legality.pbp_number;
	const expected = expectedLabel(record);

	return (
		<div
			className={
				compact
					? "grid gap-3 sm:grid-cols-3"
					: "grid gap-3 md:grid-cols-2 xl:grid-cols-3"
			}
		>
			<Section title="Plot" icon={MapPinIcon} provenance={polygon.provenance}>
				{!compact && geometry && (
					<MapView
						className="min-h-48"
						basemap="satellite"
						polygons={[
							{ id: polygon.id, geometry, label: polygon.label, tone },
						]}
					/>
				)}
				<Facts
					rows={[
						["Plot", polygon.id],
						["Region", polygon.region],
						["Province", compact ? undefined : polygon.province],
						["Country", polygon.country],
						["Area", ha(polygon.area_ha)],
						[
							"Centroid",
							compact
								? undefined
								: `${polygon.centroid_lat.toFixed(4)}, ${polygon.centroid_lon.toFixed(4)}`,
						],
						["Expected", compact ? undefined : expected],
					]}
				/>
			</Section>

			<Section
				title="Supplier & permit"
				icon={LandmarkIcon}
				provenance={legality.provenance}
			>
				<Facts
					rows={[
						["Supplier", legality.legal_name],
						["ID", compact ? undefined : record.supplier_id],
						["Permit", permit ?? "None declared"],
						["Status", legality.permit_status],
						["Expiry", legality.permit_expiry],
						["Holder", legality.declared_holder],
						[
							"Concession",
							compact ? undefined : ha(legality.concession_area_ha),
						],
						["NIB", compact ? undefined : legality.nib],
						["Owners", compact ? undefined : list(legality.beneficial_owners)],
						["Sanctions", list(legality.sanctions)],
						[
							"Certificates",
							compact ? undefined : list(legality.certifications),
						],
					]}
				/>
			</Section>

			<Section
				title="Consignment"
				icon={PackageIcon}
				provenance={consignment.provenance}
			>
				<Facts
					rows={[
						["Commodity", words(consignment.commodity)],
						["HS", consignment.hs_heading],
						["Weight", tonnes(consignment.net_weight_kg)],
						["Species", compact ? undefined : consignment.species_scientific],
						["Harvest", consignment.harvest_year],
						["Place", compact ? undefined : consignment.production_place],
					]}
				/>
			</Section>

			{!compact && operator && (
				<Section
					title="EU operator"
					icon={BuildingIcon}
					provenance={operator.provenance}
				>
					<Facts
						rows={[
							["Name", operator.legal_name],
							[
								operator.identifier_type.toUpperCase(),
								operator.identifier_value,
							],
							["City", `${operator.city}, ${operator.country}`],
							["Activity", operator.activity_type],
						]}
					/>
				</Section>
			)}

			{!compact && (options || model) && (
				<Section title="Run settings" icon={SlidersHorizontalIcon}>
					<Facts
						rows={[
							["Model", model],
							["Scenario", words(options?.scenario)],
							[
								"Sources",
								options?.refresh === undefined || options?.refresh === null
									? "Not recorded"
									: options.refresh
										? "Refreshed from sources"
										: "Cached when available",
							],
							["Batch mode", options?.batch_mode],
						]}
					/>
				</Section>
			)}
		</div>
	);
}

/** The run page's "Input" block: fetches `/runs/{id}/input` and hides itself when there is none. */
export function RunInputBlock({
	runId,
	enabled = true,
	tone,
}: {
	runId: string;
	enabled?: boolean;
	tone?: MapTone;
}) {
	const input = useQuery(runInputQuery(runId, enabled));
	if (!enabled || input.isError) return null;
	return (
		<Collapsible
			id="run-input"
			defaultOpen
			className="flex scroll-mt-4 flex-col gap-3"
		>
			<div className="flex items-center justify-between gap-2">
				<h3 className="eyebrow-sm text-muted-foreground">Input</h3>
				<CollapsibleTrigger render={<Button variant="ghost" size="sm" />}>
					<ChevronDownIcon aria-hidden="true" data-icon="inline-start" />
					What this run was given
				</CollapsibleTrigger>
			</div>
			<CollapsibleContent>
				{input.data ? (
					<RunInputPanel
						record={input.data.record}
						operator={input.data.operator}
						options={input.data.options}
						model={input.data.model}
						tone={tone}
					/>
				) : (
					<Skeleton className="h-40" />
				)}
			</CollapsibleContent>
		</Collapsible>
	);
}

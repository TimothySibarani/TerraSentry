import { useQuery } from "@tanstack/react-query";
import type { ModelMode } from "@terrasentry/api-client";
import {
	BotIcon,
	FileOutputIcon,
	FlameIcon,
	LandmarkIcon,
	type LucideIcon,
	PencilIcon,
	ScaleIcon,
	ShieldCheckIcon,
	TreesIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { MapView } from "#/components/map/map-view";
import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import { Separator } from "#/components/ui/separator";
import { healthQuery } from "#/features/health/queries";
import {
	COMMODITIES,
	currentGeometry,
	declaredArea,
	type IntakeForm,
	PERMIT_TYPES,
	type StepId,
} from "#/features/intake/form";
import { formatCoordinate } from "#/features/intake/geometry";
import { useGeometryCheck } from "#/features/intake/queries";
import { ModelSelect } from "#/features/runs/model-select";
import { formatNumber } from "#/lib/format";

interface PipelineStage {
	icon: LucideIcon;
	name: string;
	detail: string;
	source: string;
	real: boolean;
}

const LLM_LABEL: Record<ModelMode, string> = {
	scripted: "Scripted",
	bedrock: "Bedrock",
	sap: "SAP AI Core",
};

function pipeline(model: ModelMode): ReadonlyArray<PipelineStage> {
	const llm = LLM_LABEL[model];
	return [
		{
			icon: BotIcon,
			name: "Supervisor",
			detail: "Delegates the investigation to the specialists",
			source: llm,
			real: model !== "scripted",
		},
		{
			icon: TreesIcon,
			name: "Geospatial analyst",
			detail: "Annual tree-cover loss inside the plot, 2021 onward",
			source: "Hansen GFC via GFW",
			real: true,
		},
		{
			icon: FlameIcon,
			name: "Thermal analyst",
			detail: "Active-fire detections over the last 30 days",
			source: "NASA FIRMS VIIRS",
			real: true,
		},
		{
			icon: LandmarkIcon,
			name: "Legality analyst",
			detail: "Permit, sanctions, and consignment as declared",
			source: "Supplier declaration",
			real: false,
		},
		{
			icon: ScaleIcon,
			name: "Deterministic rubric",
			detail: "Scores the evidence; no model ever sets the verdict",
			source: "Code, versioned",
			real: true,
		},
		{
			icon: ShieldCheckIcon,
			name: "Independent verifier",
			detail: "Re-derives every metric and checks every citation",
			source: `Code + ${llm}`,
			real: true,
		},
		{
			icon: FileOutputIcon,
			name: "DDS writer",
			detail: "Releases the EUDR statement, or holds it for human review",
			source: "TRACES V3 shape",
			real: true,
		},
	];
}

export function ReviewStep({
	form,
	model,
	onModelChange,
	onEdit,
}: {
	form: IntakeForm;
	model: ModelMode;
	onModelChange: (model: ModelMode) => void;
	onEdit: (step: StepId) => void;
}) {
	const geometry = currentGeometry(form);
	const check = useGeometryCheck(geometry, declaredArea(form));
	const health = useQuery(healthQuery());
	const commodity = COMMODITIES.find((item) => item.value === form.commodity);
	const permit = PERMIT_TYPES.find((item) => item.value === form.permitType);
	const sourcesMissing = [
		health.data?.gfwConfigured === false ? "GFW_API_KEY" : null,
		health.data?.firmsConfigured === false ? "FIRMS_MAP_KEY" : null,
	].filter(Boolean);

	return (
		<div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
			<div className="flex min-w-0 flex-col gap-4">
				{geometry && (
					<MapView
						basemap="satellite"
						className="min-h-64"
						polygons={
							geometry.type === "Point"
								? []
								: [{ id: "plot", geometry, label: form.label, tone: "risk" }]
						}
						points={
							geometry.type === "Point"
								? [
										{
											id: "plot",
											longitude: geometry.coordinates[0] ?? 0,
											latitude: geometry.coordinates[1] ?? 0,
											label: form.label,
											tone: "risk",
										},
									]
								: []
						}
					/>
				)}
				<div className="grid gap-4 md:grid-cols-2">
					<Summary title="Plot" onEdit={() => onEdit("plot")}>
						<Row label="Name">{form.label}</Row>
						<Row label="Country">{form.country.toUpperCase()}</Row>
						<Row label="Location">
							{[form.kabupaten, form.province].filter(Boolean).join(", ") ||
								"—"}
						</Row>
						<Row label="Area">
							{check.data ? `${formatNumber(check.data.area_ha)} ha` : "—"}
						</Row>
						<Row label="Centroid">
							{check.data
								? formatCoordinate(
										check.data.centroid_lat,
										check.data.centroid_lon,
									)
								: "—"}
						</Row>
					</Summary>
					<Summary title="Supplier" onEdit={() => onEdit("supplier")}>
						<Row label="Legal name">{form.legalName}</Row>
						<Row label="NIB / NPWP">
							{[form.nib, form.npwp].filter(Boolean).join(" · ") || "—"}
						</Row>
						<Row label="Certifications">
							{form.certifications.length > 0
								? form.certifications.join(", ")
								: "None"}
						</Row>
					</Summary>
					<Summary title="Legality" onEdit={() => onEdit("legality")}>
						<Row label="Permit">
							{permit?.label}
							{form.permitType !== "none" && form.permitNumber
								? ` · ${form.permitNumber}`
								: ""}
						</Row>
						<Row label="Status">
							{form.permitType === "none" ? "—" : form.permitStatus}
						</Row>
						<Row label="Expiry">{form.permitExpiry || "Unknown"}</Row>
						<Row label="Holder">{form.declaredHolder || form.legalName}</Row>
						<Row label="Provenance">
							<Badge variant="outline">supplier-declared</Badge>
						</Row>
					</Summary>
					<Summary title="Consignment" onEdit={() => onEdit("consignment")}>
						<Row label="Commodity">{commodity?.label}</Row>
						<Row label="HS heading">{form.hsHeading || commodity?.hs}</Row>
						<Row label="Net weight">
							{formatNumber(Number(form.netWeightKg))} kg
						</Row>
						<Row label="Harvest">{form.harvestYear}</Row>
					</Summary>
				</div>
			</div>

			<aside className="flex flex-col gap-5 rounded-lg border border-border bg-card p-5">
				<ModelSelect
					id="screen-model"
					value={model}
					onChange={onModelChange}
					showHint
				/>
				<Separator />
				<div className="flex flex-col gap-3">
					<p className="eyebrow-sm text-muted-foreground">What runs next</p>
					<ol className="flex flex-col gap-3">
						{pipeline(model).map((stage) => (
							<li key={stage.name} className="flex gap-3">
								<span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border border-border bg-canvas-soft">
									<stage.icon
										aria-hidden="true"
										className="size-3.5 text-muted-foreground"
									/>
								</span>
								<span className="flex min-w-0 flex-col gap-0.5">
									<span className="flex flex-wrap items-center gap-2 text-body-sm text-foreground">
										{stage.name}
										<Badge variant={stage.real ? "compliant" : "outline"}>
											{stage.source}
										</Badge>
									</span>
									<span className="text-xs text-muted-foreground">
										{stage.detail}
									</span>
								</span>
							</li>
						))}
					</ol>
				</div>
				{sourcesMissing.length > 0 && (
					<p role="alert" className="text-xs text-status-risk">
						{sourcesMissing.join(" and ")} missing on the API: the run will
						record a data gap and route to human review.
					</p>
				)}
			</aside>
		</div>
	);
}

function Summary({
	title,
	onEdit,
	children,
}: {
	title: string;
	onEdit: () => void;
	children: ReactNode;
}) {
	return (
		<section className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
			<div className="flex items-center justify-between">
				<h3 className="eyebrow-sm text-muted-foreground">{title}</h3>
				<Button
					variant="ghost"
					size="sm"
					onClick={onEdit}
					aria-label={`Edit ${title.toLowerCase()}`}
				>
					<PencilIcon data-icon="inline-start" aria-hidden="true" />
					Edit
				</Button>
			</div>
			<dl className="flex flex-col gap-2">{children}</dl>
		</section>
	);
}

function Row({ label, children }: { label: string; children: ReactNode }) {
	return (
		<div className="grid grid-cols-[6rem_minmax(0,1fr)] gap-2 text-body-sm">
			<dt className="text-muted-foreground">{label}</dt>
			<dd className="min-w-0 break-words text-foreground">{children}</dd>
		</div>
	);
}

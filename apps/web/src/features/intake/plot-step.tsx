import {
	ClipboardPasteIcon,
	FileUpIcon,
	MapPinIcon,
	PenLineIcon,
	SparklesIcon,
} from "lucide-react";
import { type ChangeEvent, useId, useState } from "react";

import { DrawMap } from "#/components/map/draw-map";
import { MapView } from "#/components/map/map-view";
import { Alert, AlertDescription, AlertTitle } from "#/components/ui/alert";
import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import {
	Field,
	FieldDescription,
	FieldError,
	FieldGroup,
	FieldLabel,
} from "#/components/ui/field";
import { Skeleton } from "#/components/ui/skeleton";
import { Textarea } from "#/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "#/components/ui/toggle-group";
import { fieldId, TextField } from "#/features/intake/fields";
import {
	currentGeometry,
	declaredArea,
	type FieldErrors,
	type IntakeForm,
	type PlotMethod,
	SAMPLE_PLOT,
} from "#/features/intake/form";
import {
	formatCoordinate,
	type PlotGeometry,
	parseGeometryText,
} from "#/features/intake/geometry";
import { geometryIssue, useGeometryCheck } from "#/features/intake/queries";
import { formatNumber } from "#/lib/format";

const METHODS: ReadonlyArray<{
	value: PlotMethod;
	label: string;
	icon: typeof PenLineIcon;
}> = [
	{ value: "draw", label: "Draw", icon: PenLineIcon },
	{ value: "paste", label: "Paste", icon: ClipboardPasteIcon },
	{ value: "upload", label: "Upload", icon: FileUpIcon },
	{ value: "point", label: "Point ≤ 4 ha", icon: MapPinIcon },
];

const MAX_UPLOAD_BYTES = 2 * 1024 * 1024;

export function PlotStep({
	form,
	update,
	errors,
}: {
	form: IntakeForm;
	update: (patch: Partial<IntakeForm>) => void;
	errors: FieldErrors;
}) {
	const [parseError, setParseError] = useState<string | null>(null);
	const geometry = currentGeometry(form);
	const area = declaredArea(form);
	const check = useGeometryCheck(geometry, area);
	const serverIssue = geometry ? geometryIssue(check.error) : null;
	const geometryError = parseError ?? serverIssue ?? errors["plot.geometry"];
	const uploadId = useId();

	const applyText = (text: string) => {
		const result = parseGeometryText(text);
		if (result.ok) {
			setParseError(null);
			if (result.geometry.type === "Point") {
				const [lon, lat] = result.geometry.coordinates;
				update({
					plotMethod: "point",
					shape: null,
					pointLat: String(lat),
					pointLon: String(lon),
				});
			} else {
				update({ shape: result.geometry });
			}
		} else {
			setParseError(result.message);
			update({ shape: null });
		}
	};

	const onUpload = async (event: ChangeEvent<HTMLInputElement>) => {
		const file = event.target.files?.[0];
		if (!file) {
			return;
		}
		if (file.size > MAX_UPLOAD_BYTES) {
			setParseError(
				"The file is larger than 2 MB; simplify the geometry first.",
			);
			return;
		}
		update({ uploadName: file.name });
		applyText(await file.text());
	};

	const polygon: Extract<PlotGeometry, { type: "Polygon" }> | null =
		form.shape?.type === "Polygon" ? form.shape : null;

	return (
		<div className="flex flex-col gap-6">
			<div className="flex flex-wrap items-center justify-between gap-3">
				<ToggleGroup
					aria-label="How to provide the plot boundary"
					variant="outline"
					spacing={0}
					value={[form.plotMethod]}
					onValueChange={(values) => {
						const next = values[0] as PlotMethod | undefined;
						if (next) {
							setParseError(null);
							update({ plotMethod: next });
						}
					}}
				>
					{METHODS.map((method) => (
						<ToggleGroupItem key={method.value} value={method.value}>
							<method.icon data-icon="inline-start" aria-hidden="true" />
							{method.label}
						</ToggleGroupItem>
					))}
				</ToggleGroup>
				<Button
					variant="ghost"
					size="sm"
					onClick={() => {
						setParseError(null);
						update({
							plotMethod: "draw",
							shape: SAMPLE_PLOT,
							label: form.label || "Blok Siak 07",
							province: form.province || "Riau",
							kabupaten: form.kabupaten || "Siak",
						});
					}}
				>
					<SparklesIcon data-icon="inline-start" aria-hidden="true" />
					Use a sample plot in Riau
				</Button>
			</div>

			<div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_17rem]">
				<div className="flex min-w-0 flex-col gap-3">
					{form.plotMethod === "draw" && (
						<DrawMap
							value={polygon}
							onChange={(shape) => {
								setParseError(null);
								update({ shape });
							}}
						/>
					)}

					{form.plotMethod === "paste" && (
						<Field data-invalid={geometryError ? true : undefined}>
							<FieldLabel htmlFor={fieldId("plot.geometry")}>
								Plot boundary
							</FieldLabel>
							<Textarea
								id={fieldId("plot.geometry")}
								className="min-h-56 font-mono text-xs"
								spellCheck={false}
								value={form.pasteText}
								aria-invalid={geometryError ? true : undefined}
								placeholder={
									'{"type":"Polygon","coordinates":[[[101.86,0.74],…]]}\n\nor one "latitude, longitude" per line:\n0.7431, 101.8612\n0.7398, 101.8905\n0.7187, 101.8963'
								}
								onChange={(event) => {
									update({ pasteText: event.target.value });
									applyText(event.target.value);
								}}
							/>
							<FieldDescription>
								GeoJSON geometry, Feature, or single-feature collection — or one{" "}
								<span className="font-mono">latitude, longitude</span> pair per
								line, as copied from Google Maps.
							</FieldDescription>
							{geometryError && <FieldError>{geometryError}</FieldError>}
						</Field>
					)}

					{form.plotMethod === "upload" && (
						<Field data-invalid={geometryError ? true : undefined}>
							<FieldLabel htmlFor={uploadId}>GeoJSON file</FieldLabel>
							<label
								htmlFor={uploadId}
								className="flex min-h-40 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-canvas-soft/40 p-6 text-center transition-colors hover:bg-canvas-soft focus-within:ring-2 focus-within:ring-ring/50"
							>
								<FileUpIcon
									aria-hidden="true"
									className="size-5 text-muted-foreground"
								/>
								<span className="text-body-sm text-foreground">
									{form.uploadName ?? "Choose a .geojson or .json file"}
								</span>
								<span className="text-xs text-muted-foreground">
									One plot per file, WGS84, up to 2 MB. For many plots use
									portfolio import.
								</span>
								<input
									id={uploadId}
									type="file"
									accept=".geojson,.json,application/geo+json,application/json"
									className="sr-only"
									onChange={(event) => void onUpload(event)}
								/>
							</label>
							{geometryError && <FieldError>{geometryError}</FieldError>}
						</Field>
					)}

					{form.plotMethod === "point" && (
						<FieldGroup className="grid gap-4 sm:grid-cols-3">
							<TextField
								field="plot.lat"
								label="Latitude"
								required
								inputMode="decimal"
								placeholder="0.7302"
								value={form.pointLat}
								onChange={(pointLat) => update({ pointLat })}
								error={geometryError}
							/>
							<TextField
								field="plot.lon"
								label="Longitude"
								required
								inputMode="decimal"
								placeholder="101.8750"
								value={form.pointLon}
								onChange={(pointLon) => update({ pointLon })}
							/>
							<TextField
								field="plot.declared_area_ha"
								label="Plot area"
								required
								inputMode="decimal"
								suffix="ha"
								placeholder="3.5"
								value={form.declaredAreaHa}
								onChange={(declaredAreaHa) => update({ declaredAreaHa })}
								error={errors["plot.declared_area_ha"]}
								description="EUDR allows a single point only for plots up to 4 ha."
							/>
						</FieldGroup>
					)}

					{form.plotMethod !== "draw" && geometry && (
						<MapView
							basemap="satellite"
							className="min-h-72"
							polygons={
								geometry.type === "Point"
									? []
									: [
											{
												id: "plot",
												geometry,
												label: form.label || "Plot",
												tone: "risk",
											},
										]
							}
							points={
								geometry.type === "Point"
									? [
											{
												id: "plot",
												longitude: geometry.coordinates[0] ?? 0,
												latitude: geometry.coordinates[1] ?? 0,
												label: form.label || "Plot",
												tone: "risk",
											},
										]
									: []
							}
						/>
					)}
					{form.plotMethod === "draw" && geometryError && (
						<p role="alert" className="text-xs text-destructive">
							{geometryError}
						</p>
					)}
				</div>

				<MeasurementPanel
					geometry={geometry}
					pending={check.isFetching}
					report={check.data ?? null}
					issue={serverIssue}
				/>
			</div>

			<FieldGroup className="grid gap-4 md:grid-cols-3">
				<TextField
					field="plot.label"
					label="Plot name"
					required
					placeholder="Blok Siak 07"
					value={form.label}
					onChange={(label) => update({ label })}
					error={errors["plot.label"]}
					description="Used as the production place on the DDS."
				/>
				<TextField
					field="plot.province"
					label="Province"
					placeholder="Riau"
					value={form.province}
					onChange={(province) => update({ province })}
				/>
				<TextField
					field="plot.kabupaten"
					label="Regency (kabupaten)"
					placeholder="Siak"
					value={form.kabupaten}
					onChange={(kabupaten) => update({ kabupaten })}
				/>
			</FieldGroup>
		</div>
	);
}

function MeasurementPanel({
	geometry,
	pending,
	report,
	issue,
}: {
	geometry: PlotGeometry | null;
	pending: boolean;
	report: {
		area_ha: number;
		centroid_lat: number;
		centroid_lon: number;
		vertex_count: number;
		geometry_type: string;
	} | null;
	issue: string | null;
}) {
	return (
		<aside
			aria-label="Server measurement"
			aria-live="polite"
			className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4"
		>
			<div className="flex items-center justify-between gap-2">
				<p className="eyebrow-sm text-muted-foreground">Server measurement</p>
				{pending ? (
					<Badge variant="outline">Measuring…</Badge>
				) : issue ? (
					<Badge variant="risk">Rejected</Badge>
				) : report && geometry ? (
					<Badge variant="compliant">Valid</Badge>
				) : (
					<Badge variant="outline">Waiting</Badge>
				)}
			</div>
			{!geometry ? (
				<p className="text-body-sm text-muted-foreground">
					Add a boundary to see its geodesic area and centroid, measured the
					same way the rubric and DDS will.
				</p>
			) : pending && !report ? (
				<div className="flex flex-col gap-2">
					<Skeleton className="h-8 w-32" />
					<Skeleton className="h-4 w-full" />
					<Skeleton className="h-4 w-3/4" />
				</div>
			) : issue ? (
				<Alert variant="destructive">
					<AlertTitle>Geometry rejected</AlertTitle>
					<AlertDescription>{issue}</AlertDescription>
				</Alert>
			) : report ? (
				<dl className="flex flex-col gap-3">
					<div>
						<dt className="text-xs text-muted-foreground">Area (geodesic)</dt>
						<dd className="text-display-xs tabular-nums text-foreground">
							{formatNumber(report.area_ha)} ha
						</dd>
					</div>
					<div>
						<dt className="text-xs text-muted-foreground">Centroid</dt>
						<dd className="font-mono text-xs text-foreground">
							{formatCoordinate(report.centroid_lat, report.centroid_lon)}
						</dd>
					</div>
					<div className="flex gap-6">
						<div>
							<dt className="text-xs text-muted-foreground">Type</dt>
							<dd className="text-body-sm text-foreground">
								{report.geometry_type}
							</dd>
						</div>
						<div>
							<dt className="text-xs text-muted-foreground">Vertices</dt>
							<dd className="text-body-sm tabular-nums text-foreground">
								{report.vertex_count}
							</dd>
						</div>
					</div>
					<div>
						<dt className="sr-only">EUDR geolocation rule</dt>
						<dd className="text-xs text-muted-foreground">
							{report.geometry_type === "Point"
								? "Point accepted (≤ 4 ha). Sources query a circle of the declared area."
								: report.area_ha > 4
									? "Above 4 ha: the DDS carries the full polygon."
									: "At or below 4 ha: the DDS carries the centroid point."}
						</dd>
					</div>
				</dl>
			) : null}
		</aside>
	);
}

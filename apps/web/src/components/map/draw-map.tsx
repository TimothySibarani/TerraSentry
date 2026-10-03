import { EyeIcon, EyeOffIcon, PentagonIcon, Trash2Icon } from "lucide-react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import type { TerraDraw } from "terra-draw";

import {
	LOSS_LAYER_ID,
	satelliteStyle,
	tokenColor,
} from "#/components/map/basemap";
import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import { Skeleton } from "#/components/ui/skeleton";
import type { PlotGeometry } from "#/features/intake/geometry";
import { collectPositions } from "#/features/intake/geometry";
import { cn } from "#/lib/utils";

import "maplibre-gl/dist/maplibre-gl.css";

type Polygon = Extract<PlotGeometry, { type: "Polygon" }>;

const INDONESIA: [number, number] = [113.5, -1.2];

function bounds(geometry: PlotGeometry): [[number, number], [number, number]] {
	const positions = collectPositions(geometry);
	const lons = positions.map((position) => position[0] ?? 0);
	const lats = positions.map((position) => position[1] ?? 0);
	return [
		[Math.min(...lons), Math.min(...lats)],
		[Math.max(...lons), Math.max(...lats)],
	];
}

/**
 * Satellite map with a polygon editor (terra-draw). Exactly one plot polygon
 * is kept: drawing a new one replaces the old. `value` is controlled, so a
 * pasted or uploaded polygon appears here and becomes editable.
 */
export function DrawMap({
	value,
	onChange,
	className,
}: {
	value: Polygon | null;
	onChange: (geometry: Polygon | null) => void;
	className?: string;
}) {
	const containerRef = useRef<HTMLDivElement>(null);
	const mapRef = useRef<MapLibreMap | null>(null);
	const drawRef = useRef<TerraDraw | null>(null);
	const onChangeRef = useRef(onChange);
	// Serialised geometry last emitted by the editor, so echoes of our own
	// onChange do not reload (and deselect) the feature being edited.
	const emittedRef = useRef<string | null>(null);
	// True while we mutate the store ourselves; those events are not user edits.
	const syncingRef = useRef(false);
	const [ready, setReady] = useState(false);
	const [failed, setFailed] = useState(false);
	const [drawing, setDrawing] = useState(false);
	const [showLoss, setShowLoss] = useState(true);

	onChangeRef.current = onChange;

	useEffect(() => {
		let cancelled = false;
		let map: MapLibreMap | null = null;
		let draw: TerraDraw | null = null;
		void (async () => {
			try {
				const [maplibregl, terra, adapterModule, worker] = await Promise.all([
					import("maplibre-gl"),
					import("terra-draw"),
					import("terra-draw-maplibre-gl-adapter"),
					import("maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url"),
				]);
				if (cancelled || !containerRef.current) {
					return;
				}
				// MapLibre v6 cannot derive its worker URL inside Vite's module
				// graph; without this, GeoJSON sources (the drawn plot) never tile.
				maplibregl.setWorkerUrl(worker.default);
				map = new maplibregl.Map({
					container: containerRef.current,
					style: satelliteStyle({ showLoss: true }),
					center: INDONESIA,
					zoom: 4,
					attributionControl: { compact: true },
				});
				map.addControl(
					new maplibregl.NavigationControl({ showCompass: false }),
					"top-right",
				);
				map.addControl(
					new maplibregl.ScaleControl({ unit: "metric" }),
					"bottom-left",
				);
				mapRef.current = map;
				const loadedMap = map;
				loadedMap.on("load", () => {
					if (cancelled) {
						return;
					}
					const stroke = tokenColor("--color-accent-sunset", "#ff7a17");
					const ink = tokenColor("--color-ink", "#ffffff");
					draw = new terra.TerraDraw({
						adapter: new adapterModule.TerraDrawMapLibreGLAdapter({
							map: loadedMap,
						}),
						modes: [
							new terra.TerraDrawPolygonMode({
								editable: true,
								validation: (feature, { updateType }) =>
									updateType === "finish" || updateType === "commit"
										? terra.ValidateNotSelfIntersecting(feature)
										: { valid: true },
								styles: {
									fillColor: stroke,
									fillOpacity: 0.18,
									outlineColor: stroke,
									outlineWidth: 2,
									closingPointColor: ink,
									closingPointOutlineColor: stroke,
									editedPointColor: ink,
									coordinatePointColor: ink,
									coordinatePointOutlineColor: stroke,
								},
							}),
						],
					});
					draw.start();
					draw.setMode("polygon");
					const emit = () => {
						const features = draw?.getSnapshot() ?? [];
						const polygon = features
							.filter((feature) => feature.geometry.type === "Polygon")
							.at(-1);
						const geometry = polygon
							? ({
									type: "Polygon",
									coordinates: polygon.geometry.coordinates,
								} as Polygon)
							: null;
						emittedRef.current = geometry ? JSON.stringify(geometry) : null;
						onChangeRef.current(geometry);
					};
					draw.on("finish", (id) => {
						// One plot per submission: a newly closed polygon replaces the old.
						const others = (draw?.getSnapshot() ?? [])
							.map((feature) => feature.id)
							.filter(
								(featureId): featureId is string | number =>
									featureId !== undefined && featureId !== id,
							);
						if (others.length > 0) {
							draw?.removeFeatures(others);
						}
						setDrawing(false);
						emit();
					});
					draw.on("change", (_ids, type) => {
						if (syncingRef.current) {
							return;
						}
						if (type === "update" || type === "delete") {
							emit();
						}
						if (type === "create") {
							setDrawing(true);
						}
					});
					drawRef.current = draw;
					setReady(true);
				});
				loadedMap.on("error", () => {
					if (!cancelled && !loadedMap.loaded()) {
						setFailed(true);
					}
				});
			} catch {
				if (!cancelled) {
					setFailed(true);
				}
			}
		})();
		return () => {
			cancelled = true;
			drawRef.current = null;
			mapRef.current = null;
			draw?.stop();
			map?.remove();
		};
	}, []);

	// Controlled value: load external geometry (paste/upload) into the editor.
	useEffect(() => {
		const draw = drawRef.current;
		const map = mapRef.current;
		if (!ready || !draw || !map) {
			return;
		}
		const serialised = value ? JSON.stringify(value) : null;
		if (serialised === emittedRef.current) {
			return;
		}
		emittedRef.current = serialised;
		syncingRef.current = true;
		draw.clear();
		if (value && value.coordinates.length === 1) {
			const ring = value.coordinates[0] ?? [];
			draw.addFeatures([
				{
					type: "Feature",
					geometry: {
						type: "Polygon",
						coordinates: [
							ring.map((position) => [position[0] ?? 0, position[1] ?? 0]),
						],
					},
					properties: { mode: "polygon" },
				},
			]);
			map.fitBounds(bounds(value), { padding: 64, duration: 600, maxZoom: 15 });
		}
		syncingRef.current = false;
		setDrawing(false);
	}, [value, ready]);

	useEffect(() => {
		const map = mapRef.current;
		if (ready && map?.getLayer(LOSS_LAYER_ID)) {
			map.setLayoutProperty(
				LOSS_LAYER_ID,
				"visibility",
				showLoss ? "visible" : "none",
			);
		}
	}, [showLoss, ready]);

	const clear = () => {
		drawRef.current?.clear();
		drawRef.current?.setMode("polygon");
		emittedRef.current = null;
		setDrawing(false);
		onChange(null);
	};

	return (
		<section
			aria-label="Plot drawing map"
			className={cn(
				"relative min-h-[28rem] w-full overflow-hidden rounded-lg border border-border bg-canvas-card",
				className,
			)}
		>
			<div className="absolute inset-0">
				<div ref={containerRef} className="h-full w-full" />
			</div>
			{!ready && !failed && (
				<Skeleton className="absolute inset-0 rounded-none" />
			)}
			{failed && (
				<div className="absolute inset-0 flex items-center justify-center p-6 text-center">
					<p className="text-body-sm text-muted-foreground">
						The map could not load. Paste coordinates or upload a GeoJSON file
						instead.
					</p>
				</div>
			)}
			{ready && (
				<>
					<div className="absolute top-3 left-3 flex flex-wrap items-center gap-2">
						<Badge variant="outline" className="bg-background/80 backdrop-blur">
							<PentagonIcon data-icon="inline-start" aria-hidden="true" />
							{value
								? "Drag corners to edit · click the map to redraw"
								: drawing
									? "Click the first corner or press Enter to close"
									: "Click on the map to place the first corner"}
						</Badge>
					</div>
					<div className="absolute bottom-8 right-3 flex flex-col items-end gap-2">
						<Button
							size="sm"
							variant="outline"
							className="bg-background/80 backdrop-blur"
							aria-pressed={showLoss}
							onClick={() => setShowLoss((current) => !current)}
						>
							{showLoss ? (
								<EyeIcon data-icon="inline-start" aria-hidden="true" />
							) : (
								<EyeOffIcon data-icon="inline-start" aria-hidden="true" />
							)}
							Tree-cover loss 2021+
						</Button>
						{(value || drawing) && (
							<Button
								size="sm"
								variant="outline"
								className="bg-background/80 backdrop-blur"
								onClick={clear}
							>
								<Trash2Icon data-icon="inline-start" aria-hidden="true" />
								Clear plot
							</Button>
						)}
					</div>
				</>
			)}
		</section>
	);
}

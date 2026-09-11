import type {
	GeoJSONSource,
	MapGeoJSONFeature,
	Map as MapLibreMap,
} from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import { Skeleton } from "#/components/ui/skeleton";
import type { GeoJsonGeometry } from "#/features/runs/evidence";

import "maplibre-gl/dist/maplibre-gl.css";

const COLORS = {
	compliant: "#a0c3ec",
	risk: "#ff7a17",
	review: "#c4b5fd",
	neutral: "#7d8187",
} as const;

export type MapTone = keyof typeof COLORS;

export interface MapPolygon {
	id: string;
	geometry: GeoJsonGeometry;
	label: string;
	detail?: string;
	tone: MapTone;
}

export interface MapPoint {
	id: string;
	longitude: number;
	latitude: number;
	label: string;
	detail?: string;
	frp?: number | null;
	tone?: MapTone;
}

const FALLBACK_STYLE = {
	version: 8 as const,
	sources: {},
	layers: [
		{
			id: "background",
			type: "background" as const,
			paint: { "background-color": "#0a0a0a" },
		},
	],
};

const POLYGON_SOURCE = "ts-polygons";
const POLYGON_FILL = "ts-polygons-fill";
const POLYGON_LINE = "ts-polygons-line";
const POINT_SOURCE = "ts-hotspots";
const POINT_LAYER = "ts-hotspots-circle";

function polygonFeatures(polygons: ReadonlyArray<MapPolygon>) {
	return {
		type: "FeatureCollection" as const,
		features: polygons.map((polygon) => ({
			type: "Feature" as const,
			id: polygon.id,
			properties: {
				label: polygon.label,
				detail: polygon.detail ?? "",
				color: COLORS[polygon.tone],
			},
			geometry: polygon.geometry,
		})),
	};
}

function pointFeatures(points: ReadonlyArray<MapPoint>) {
	return {
		type: "FeatureCollection" as const,
		features: points.map((point) => ({
			type: "Feature" as const,
			id: point.id,
			properties: {
				label: point.label,
				detail: point.detail ?? "",
				frp: point.frp ?? 0,
				color: COLORS[point.tone ?? "risk"],
			},
			geometry: {
				type: "Point" as const,
				coordinates: [point.longitude, point.latitude],
			},
		})),
	};
}

function collectCoordinates(value: unknown, acc: Array<[number, number]>) {
	if (!Array.isArray(value)) {
		return;
	}
	if (
		value.length >= 2 &&
		typeof value[0] === "number" &&
		typeof value[1] === "number"
	) {
		acc.push([value[0], value[1]]);
		return;
	}
	for (const child of value) {
		collectCoordinates(child, acc);
	}
}

function computeBounds(
	polygons: ReadonlyArray<MapPolygon>,
	points: ReadonlyArray<MapPoint>,
): [[number, number], [number, number]] | null {
	const coordinates: Array<[number, number]> = [];
	for (const polygon of polygons) {
		collectCoordinates(polygon.geometry.coordinates, coordinates);
	}
	for (const point of points) {
		coordinates.push([point.longitude, point.latitude]);
	}
	if (coordinates.length === 0) {
		return null;
	}
	let minLng = coordinates[0]?.[0] ?? 0;
	let minLat = coordinates[0]?.[1] ?? 0;
	let maxLng = minLng;
	let maxLat = minLat;
	for (const [lng, lat] of coordinates) {
		minLng = Math.min(minLng, lng);
		minLat = Math.min(minLat, lat);
		maxLng = Math.max(maxLng, lng);
		maxLat = Math.max(maxLat, lat);
	}
	if (minLng === maxLng && minLat === maxLat) {
		return null;
	}
	return [
		[minLng, minLat],
		[maxLng, maxLat],
	];
}

function popupElement(
	feature: MapGeoJSONFeature,
	fallbackTitle: string,
): HTMLElement {
	const properties = feature.properties ?? {};
	const container = document.createElement("div");
	container.className = "flex flex-col gap-1 p-1";
	const title = document.createElement("p");
	title.className = "text-xs font-medium text-foreground";
	title.textContent = String(properties.label ?? fallbackTitle);
	container.append(title);
	const detail = String(properties.detail ?? "").trim();
	if (detail) {
		const body = document.createElement("p");
		body.className = "text-[11px] text-muted-foreground";
		body.textContent = detail;
		container.append(body);
	}
	return container;
}

export function MapView({
	polygons,
	points = [],
	className,
}: {
	polygons: ReadonlyArray<MapPolygon>;
	points?: ReadonlyArray<MapPoint>;
	className?: string;
}) {
	const containerRef = useRef<HTMLDivElement>(null);
	const mapRef = useRef<MapLibreMap | null>(null);
	const maplibreRef = useRef<typeof import("maplibre-gl") | null>(null);
	const readyRef = useRef(false);
	const [ready, setReady] = useState(false);
	const [failed, setFailed] = useState(false);

	useEffect(() => {
		let cancelled = false;
		let map: MapLibreMap | null = null;
		void (async () => {
			try {
				const maplibregl = await import("maplibre-gl");
				if (cancelled || !containerRef.current) {
					return;
				}
				maplibreRef.current = maplibregl;
				const styleUrl = import.meta.env.VITE_MAP_STYLE_URL;
				map = new maplibregl.Map({
					container: containerRef.current,
					style: styleUrl && styleUrl.length > 0 ? styleUrl : FALLBACK_STYLE,
					center: [101.5, -1.5],
					zoom: 4,
					attributionControl: styleUrl ? { compact: true } : false,
				});
				map.addControl(
					new maplibregl.NavigationControl({ showCompass: false }),
					"top-right",
				);
				map.on("load", () => {
					readyRef.current = true;
					if (!cancelled) {
						setReady(true);
					}
				});
				map.on("error", () => {
					// Style/tile errors after a successful load are non-fatal; only a
					// map that never reached "load" gets the fallback message.
					if (!cancelled && !readyRef.current) {
						setFailed(true);
					}
				});
				mapRef.current = map;
			} catch {
				if (!cancelled) {
					setFailed(true);
				}
			}
		})();
		return () => {
			cancelled = true;
			mapRef.current = null;
			maplibreRef.current = null;
			map?.remove();
		};
	}, []);

	useEffect(() => {
		const map = mapRef.current;
		if (!map || !ready) {
			return;
		}
		const polygonData = polygonFeatures(polygons);
		const pointData = pointFeatures(points);
		const existingPolygons = map.getSource(POLYGON_SOURCE) as
			| GeoJSONSource
			| undefined;
		if (existingPolygons) {
			void existingPolygons.setData(polygonData);
		} else {
			map.addSource(POLYGON_SOURCE, {
				type: "geojson",
				data: polygonData,
			} as Parameters<MapLibreMap["addSource"]>[1]);
			map.addLayer({
				id: POLYGON_FILL,
				type: "fill",
				source: POLYGON_SOURCE,
				paint: {
					"fill-color": ["get", "color"],
					"fill-opacity": 0.35,
				},
			});
			map.addLayer({
				id: POLYGON_LINE,
				type: "line",
				source: POLYGON_SOURCE,
				paint: {
					"line-color": ["get", "color"],
					"line-width": 1.5,
					"line-opacity": 0.9,
				},
			});
		}
		const existingPoints = map.getSource(POINT_SOURCE) as
			| GeoJSONSource
			| undefined;
		if (existingPoints) {
			void existingPoints.setData(pointData);
		} else {
			map.addSource(POINT_SOURCE, {
				type: "geojson",
				data: pointData,
			} as Parameters<MapLibreMap["addSource"]>[1]);
			map.addLayer({
				id: POINT_LAYER,
				type: "circle",
				source: POINT_SOURCE,
				paint: {
					"circle-color": ["get", "color"],
					"circle-radius": [
						"interpolate",
						["linear"],
						["coalesce", ["get", "frp"], 0],
						0,
						3,
						50,
						9,
					],
					"circle-opacity": 0.85,
					"circle-stroke-color": "#0a0a0a",
					"circle-stroke-width": 1,
				},
			});
		}

		const bounds = computeBounds(polygons, points);
		if (bounds) {
			map.fitBounds(bounds, { padding: 48, duration: 600, maxZoom: 12 });
		} else if (points.length > 0 && points[0]) {
			map.easeTo({
				center: [points[0].longitude, points[0].latitude],
				zoom: 10,
				duration: 600,
			});
		} else if (polygons.length > 0) {
			const coordinates: Array<[number, number]> = [];
			for (const polygon of polygons) {
				collectCoordinates(polygon.geometry.coordinates, coordinates);
			}
			const first = coordinates[0];
			if (first) {
				map.easeTo({ center: first, zoom: 10, duration: 600 });
			}
		}
	}, [polygons, points, ready]);

	useEffect(() => {
		const map = mapRef.current;
		const maplibregl = maplibreRef.current;
		if (!map || !ready || !maplibregl) {
			return;
		}
		const handlePolygonClick = (event: {
			lngLat: { lng: number; lat: number };
			features?: MapGeoJSONFeature[];
		}) => {
			const feature = event.features?.[0];
			if (!feature) {
				return;
			}
			new maplibregl.Popup({ closeButton: false, maxWidth: "280px" })
				.setLngLat([event.lngLat.lng, event.lngLat.lat])
				.setDOMContent(popupElement(feature, "Parcel"))
				.addTo(map);
		};
		const handlePointClick = (event: {
			lngLat: { lng: number; lat: number };
			features?: MapGeoJSONFeature[];
		}) => {
			const feature = event.features?.[0];
			if (!feature) {
				return;
			}
			new maplibregl.Popup({ closeButton: false, maxWidth: "280px" })
				.setLngLat([event.lngLat.lng, event.lngLat.lat])
				.setDOMContent(popupElement(feature, "Fire detection"))
				.addTo(map);
		};
		const enter = () => {
			map.getCanvas().style.cursor = "pointer";
		};
		const leave = () => {
			map.getCanvas().style.cursor = "";
		};
		if (map.getLayer(POLYGON_FILL)) {
			map.on("click", POLYGON_FILL, handlePolygonClick);
			map.on("mouseenter", POLYGON_FILL, enter);
			map.on("mouseleave", POLYGON_FILL, leave);
		}
		if (map.getLayer(POINT_LAYER)) {
			map.on("click", POINT_LAYER, handlePointClick);
			map.on("mouseenter", POINT_LAYER, enter);
			map.on("mouseleave", POINT_LAYER, leave);
		}
		return () => {
			if (map.getLayer(POLYGON_FILL)) {
				map.off("click", POLYGON_FILL, handlePolygonClick);
				map.off("mouseenter", POLYGON_FILL, enter);
				map.off("mouseleave", POLYGON_FILL, leave);
			}
			if (map.getLayer(POINT_LAYER)) {
				map.off("click", POINT_LAYER, handlePointClick);
				map.off("mouseenter", POINT_LAYER, enter);
				map.off("mouseleave", POINT_LAYER, leave);
			}
		};
	}, [ready]);

	const isEmpty = polygons.length === 0 && points.length === 0;

	return (
		<section
			aria-label="Map of parcel geometry and fire hotspots"
			className={
				"relative min-h-72 w-full overflow-hidden rounded-lg border border-border bg-canvas-card " +
				(className ?? "")
			}
		>
			<div ref={containerRef} className="absolute inset-0" />
			{!ready && !failed && (
				<Skeleton className="absolute inset-0 rounded-none" />
			)}
			{failed && (
				<div className="absolute inset-0 flex items-center justify-center p-6 text-center">
					<p className="text-body-sm text-muted-foreground">
						The map could not be loaded in this browser. The evidence tables
						remain available.
					</p>
				</div>
			)}
			{ready && isEmpty && (
				<div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6">
					<p className="text-body-sm text-muted-foreground">
						No geometry or hotspots recorded for this view.
					</p>
				</div>
			)}
		</section>
	);
}

import type { StyleSpecification } from "maplibre-gl";

/**
 * Basemaps for plot drawing and review. MapLibre paints on a canvas and
 * cannot read CSS variables, so colours are resolved from the design tokens
 * in `styles.css` at runtime (with the DESIGN.md values as a fallback).
 */

const DEFAULT_IMAGERY =
	"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const DEFAULT_LABELS =
	"https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}";
/**
 * GFW's public Hansen tree-cover-loss tiles, filtered to the EUDR window.
 * `render_type=true_color` is required: the API defaults to `encoded` tiles,
 * which carry loss-year/density in raw pixel channels for GFW's own decoder
 * and render as a near-opaque blanket if displayed directly.
 */
const TREE_COVER_LOSS =
	"https://tiles.globalforestwatch.org/umd_tree_cover_loss/latest/dynamic/{z}/{x}/{y}.png?start_year=2021&render_type=true_color";

export const LOSS_LAYER_ID = "ts-tree-cover-loss";

export function tokenColor(name: string, fallback: `#${string}`): `#${string}` {
	if (typeof document === "undefined") {
		return fallback;
	}
	const value = getComputedStyle(document.documentElement)
		.getPropertyValue(name)
		.trim();
	return /^#[0-9a-f]{3,8}$/i.test(value) ? (value as `#${string}`) : fallback;
}

/**
 * Satellite imagery + place labels + an optional tree-cover-loss overlay.
 * `VITE_SATELLITE_TILES_URL` swaps the imagery (e.g. Amazon Location raster).
 */
export function satelliteStyle({
	showLoss,
}: {
	showLoss: boolean;
}): StyleSpecification {
	const imagery =
		import.meta.env.VITE_SATELLITE_TILES_URL?.trim() || DEFAULT_IMAGERY;
	const usingDefault = imagery === DEFAULT_IMAGERY;
	return {
		version: 8,
		sources: {
			imagery: {
				type: "raster",
				tiles: [imagery],
				tileSize: 256,
				maxzoom: 18,
				attribution: usingDefault
					? "Imagery © Esri, Maxar, Earthstar Geographics"
					: "",
			},
			labels: {
				type: "raster",
				tiles: [DEFAULT_LABELS],
				tileSize: 256,
				maxzoom: 18,
			},
			loss: {
				type: "raster",
				tiles: [TREE_COVER_LOSS],
				tileSize: 256,
				maxzoom: 12,
				attribution:
					"Tree cover loss 2021+ — Hansen/UMD/Google/USGS/NASA via Global Forest Watch",
			},
		},
		layers: [
			{
				id: "background",
				type: "background",
				paint: { "background-color": tokenColor("--color-canvas", "#0a0a0a") },
			},
			{
				id: "imagery",
				type: "raster",
				source: "imagery",
				paint: { "raster-saturation": -0.25, "raster-brightness-max": 0.85 },
			},
			{
				id: LOSS_LAYER_ID,
				type: "raster",
				source: "loss",
				layout: { visibility: showLoss ? "visible" : "none" },
				paint: { "raster-opacity": 0.8 },
			},
			{ id: "labels", type: "raster", source: "labels" },
		],
	};
}

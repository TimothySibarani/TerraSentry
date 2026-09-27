import { Option, Schema } from "effect";

/**
 * Client-side plot geometry parsing. This is advisory only: it gives instant
 * feedback while typing, and the server (`POST /records/validate-geometry`)
 * stays authoritative for validity, area, and the EUDR 4 ha rule.
 */

const Position = Schema.Tuple([Schema.Finite, Schema.Finite]).pipe(
	Schema.check(
		Schema.makeFilter(
			([lon, lat]) =>
				(lon >= -180 && lon <= 180 && lat >= -90 && lat <= 90) ||
				"coordinates must be longitude/latitude in WGS84",
		),
	),
);
// GeoJSON allows an optional third (altitude) value; keep lon/lat only.
const LooseCoord = Schema.Array(Schema.Finite).pipe(
	Schema.check(
		Schema.makeFilter(
			(values) => values.length >= 2 || "each position needs lon and lat",
		),
	),
);
const Ring = Schema.Array(LooseCoord).pipe(
	Schema.check(
		Schema.makeFilter(
			(ring) => ring.length >= 4 || "a polygon ring needs at least 4 points",
		),
	),
);

export const PolygonGeometry = Schema.Struct({
	type: Schema.Literal("Polygon"),
	coordinates: Schema.Array(Ring),
});
export const MultiPolygonGeometry = Schema.Struct({
	type: Schema.Literal("MultiPolygon"),
	coordinates: Schema.Array(Schema.Array(Ring)),
});
export const PointGeometry = Schema.Struct({
	type: Schema.Literal("Point"),
	coordinates: LooseCoord,
});

export const PlotGeometry = Schema.Union([
	PolygonGeometry,
	MultiPolygonGeometry,
	PointGeometry,
]);
export type PlotGeometry = typeof PlotGeometry.Type;

const FeatureLike = Schema.Struct({
	type: Schema.Literal("Feature"),
	geometry: Schema.Unknown,
});
const FeatureCollectionLike = Schema.Struct({
	type: Schema.Literal("FeatureCollection"),
	features: Schema.Array(Schema.Unknown),
});

export type ParseResult =
	| { readonly ok: true; readonly geometry: PlotGeometry }
	| { readonly ok: false; readonly message: string };

const decodeGeometry = Schema.decodeUnknownOption(PlotGeometry);
const decodePosition = Schema.decodeUnknownOption(Position);

function fromGeoJson(value: unknown, depth = 0): ParseResult {
	const feature = Schema.decodeUnknownOption(FeatureLike)(value);
	if (Option.isSome(feature) && depth < 2) {
		return fromGeoJson(feature.value.geometry, depth + 1);
	}
	const collection = Schema.decodeUnknownOption(FeatureCollectionLike)(value);
	if (Option.isSome(collection) && depth < 2) {
		if (collection.value.features.length !== 1) {
			return {
				ok: false,
				message: `the collection has ${collection.value.features.length} features; screen one plot at a time or use portfolio import`,
			};
		}
		return fromGeoJson(collection.value.features[0], depth + 1);
	}
	const geometry = decodeGeometry(value);
	if (Option.isNone(geometry)) {
		return {
			ok: false,
			message:
				"expected a GeoJSON Polygon, MultiPolygon, or Point (or a Feature wrapping one)",
		};
	}
	const outOfRange = collectPositions(geometry.value).some((position) =>
		Option.isNone(decodePosition(position.slice(0, 2))),
	);
	if (outOfRange) {
		return {
			ok: false,
			message:
				"coordinates are outside WGS84 range; GeoJSON order is [longitude, latitude]",
		};
	}
	return { ok: true, geometry: geometry.value };
}

/** Lines of `lat, lon` (Google Maps copy order), closed automatically. */
function fromLatLonLines(text: string): ParseResult {
	const lines = text
		.split(/\r?\n/)
		.map((line) => line.trim())
		.filter(Boolean);
	const ring: Array<[number, number]> = [];
	for (const [index, line] of lines.entries()) {
		const parts = line
			.split(/[\s,;]+/)
			.filter(Boolean)
			.map(Number);
		const [lat, lon] = parts;
		if (
			parts.length !== 2 ||
			lat === undefined ||
			lon === undefined ||
			Option.isNone(decodePosition([lon, lat]))
		) {
			return {
				ok: false,
				message: `line ${index + 1}: expected "latitude, longitude" in decimal degrees`,
			};
		}
		ring.push([lon, lat]);
	}
	if (ring.length === 1 && ring[0]) {
		return { ok: true, geometry: { type: "Point", coordinates: ring[0] } };
	}
	const first = ring[0];
	const last = ring.at(-1);
	if (first && last && (first[0] !== last[0] || first[1] !== last[1])) {
		ring.push(first);
	}
	if (ring.length < 4) {
		return {
			ok: false,
			message: "a polygon needs at least 3 distinct corners",
		};
	}
	return { ok: true, geometry: { type: "Polygon", coordinates: [ring] } };
}

/** Parse pasted or uploaded text: GeoJSON first, then `lat, lon` lines. */
export function parseGeometryText(text: string): ParseResult {
	const trimmed = text.trim();
	if (!trimmed) {
		return { ok: false, message: "paste GeoJSON or coordinates" };
	}
	if (trimmed.startsWith("{")) {
		try {
			return fromGeoJson(JSON.parse(trimmed));
		} catch {
			return { ok: false, message: "this is not valid JSON" };
		}
	}
	return fromLatLonLines(trimmed);
}

export function collectPositions(
	geometry: PlotGeometry,
): ReadonlyArray<ReadonlyArray<number>> {
	switch (geometry.type) {
		case "Point":
			return [geometry.coordinates];
		case "Polygon":
			return geometry.coordinates.flat();
		case "MultiPolygon":
			return geometry.coordinates.flat(2);
	}
}

export function vertexCount(geometry: PlotGeometry): number {
	return collectPositions(geometry).length;
}

export function formatCoordinate(lat: number, lon: number): string {
	const ns = lat >= 0 ? "N" : "S";
	const ew = lon >= 0 ? "E" : "W";
	return `${Math.abs(lat).toFixed(5)}° ${ns}, ${Math.abs(lon).toFixed(5)}° ${ew}`;
}

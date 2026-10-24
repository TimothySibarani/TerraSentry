import { Option, Schema } from "effect";

/**
 * Client-side check of a supplier portfolio file before upload. It only catches a wrong file
 * early (missing columns, not a FeatureCollection); the server stays authoritative and
 * reports every row it rejects.
 */

export const PORTFOLIO_MAX_BYTES = 5 * 1024 * 1024;
export const PORTFOLIO_MAX_ROWS = 500;

/** Columns every CSV row needs; the server accepts `supplier` as an alias for `legal_name`. */
const REQUIRED_COLUMNS: ReadonlyArray<{
	label: string;
	anyOf: ReadonlyArray<string>;
}> = [
	{ label: "country", anyOf: ["country"] },
	{ label: "legal_name", anyOf: ["legal_name", "supplier"] },
	{ label: "commodity", anyOf: ["commodity"] },
	{ label: "description", anyOf: ["description"] },
	{ label: "net_weight_kg", anyOf: ["net_weight_kg"] },
	{ label: "harvest_year", anyOf: ["harvest_year"] },
];

export interface PortfolioPreview {
	readonly kind: "csv" | "geojson" | "unsupported";
	readonly rows: number;
	/** Problems that make an upload pointless; empty means "looks importable". */
	readonly problems: ReadonlyArray<string>;
}

const FeatureCollection = Schema.Struct({
	type: Schema.Literal("FeatureCollection"),
	features: Schema.Array(Schema.Unknown),
});

function delimiterOf(header: string): string {
	const counts = [",", ";", "\t"].map(
		(delimiter) => [delimiter, header.split(delimiter).length] as const,
	);
	return counts.reduce((best, next) => (next[1] > best[1] ? next : best))[0];
}

function previewCsv(text: string): PortfolioPreview {
	const lines = text
		.replace(/^﻿/, "")
		.split(/\r?\n/)
		.filter((line) => line.trim() !== "");
	const header = lines[0];
	if (header === undefined) {
		return { kind: "csv", rows: 0, problems: ["The file is empty."] };
	}
	const columns = new Set(
		header.split(delimiterOf(header)).map((name) => name.trim().toLowerCase()),
	);
	const problems = REQUIRED_COLUMNS.filter(
		(column) => !column.anyOf.some((name) => columns.has(name)),
	).map((column) => `Missing column: ${column.label}`);
	if (!columns.has("wkt") && !(columns.has("lat") && columns.has("lon"))) {
		problems.push("Missing plot location: add a wkt column, or lat and lon");
	}
	const rows = lines.length - 1;
	if (rows === 0) {
		problems.push("The file has a header but no rows.");
	}
	if (rows > PORTFOLIO_MAX_ROWS) {
		problems.push(
			`${rows} rows; import at most ${PORTFOLIO_MAX_ROWS} per file.`,
		);
	}
	return { kind: "csv", rows, problems };
}

function previewGeoJson(text: string): PortfolioPreview {
	let parsed: unknown;
	try {
		parsed = JSON.parse(text);
	} catch {
		return {
			kind: "geojson",
			rows: 0,
			problems: ["The file is not valid JSON."],
		};
	}
	const collection = Option.getOrNull(
		Schema.decodeUnknownOption(FeatureCollection)(parsed),
	);
	if (collection === null) {
		return {
			kind: "geojson",
			rows: 0,
			problems: ["GeoJSON import needs a FeatureCollection."],
		};
	}
	const rows = collection.features.length;
	const problems =
		rows === 0
			? ["The FeatureCollection has no features."]
			: rows > PORTFOLIO_MAX_ROWS
				? [`${rows} features; import at most ${PORTFOLIO_MAX_ROWS} per file.`]
				: [];
	return { kind: "geojson", rows, problems };
}

export function previewPortfolio(
	filename: string,
	text: string,
): PortfolioPreview {
	const name = filename.toLowerCase();
	if (name.endsWith(".geojson") || name.endsWith(".json")) {
		return previewGeoJson(text);
	}
	if (name.endsWith(".csv") || name.endsWith(".txt")) {
		return previewCsv(text);
	}
	return {
		kind: "unsupported",
		rows: 0,
		problems: ["Use a .csv or .geojson file."],
	};
}

/** The downloadable starter file: a wood-pulp row (data/templates/portfolio.csv is the palm-oil variant). */
export const PORTFOLIO_TEMPLATE_CSV = [
	"country,label,wkt,legal_name,commodity,description,net_weight_kg,harvest_year,permit_type,permit_number,permit_expiry,declared_holder",
	'ID,Example plot,"POLYGON((106.82 -6.17,106.821 -6.17,106.821 -6.169,106.82 -6.169,106.82 -6.17))",Example supplier,wood,Wood pulp,25000,2026,pbph,DECLARED-EXAMPLE,2027-12-31,Example supplier',
	"",
].join("\n");

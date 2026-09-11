import type { EvidenceEntry } from "@terrasentry/api-client";
import { Option, Schema } from "effect";

/** A FIRMS detection as persisted in the evidence ledger. */
export const FireDetection = Schema.Struct({
	latitude: Schema.Number,
	longitude: Schema.Number,
	acq_date: Schema.String,
	acq_time: Schema.optional(Schema.String),
	brightness: Schema.optional(Schema.NullOr(Schema.Number)),
	confidence: Schema.optional(Schema.NullOr(Schema.String)),
	frp: Schema.optional(Schema.NullOr(Schema.Number)),
	satellite: Schema.optional(Schema.NullOr(Schema.String)),
	daynight: Schema.optional(Schema.NullOr(Schema.String)),
});
export type FireDetection = typeof FireDetection.Type;

export const GeoJsonGeometry = Schema.Struct({
	type: Schema.Literals(["Polygon", "MultiPolygon"]),
	coordinates: Schema.Unknown,
});
export type GeoJsonGeometry = typeof GeoJsonGeometry.Type;

export const LossYear = Schema.Struct({
	year: Schema.Int,
	loss_ha: Schema.Number,
});
export type LossYear = typeof LossYear.Type;

export function findEvidence(
	entries: ReadonlyArray<EvidenceEntry>,
	claim: string,
): EvidenceEntry | undefined {
	return entries.find((entry) => entry.claim === claim);
}

export function decodeGeometry(value: unknown): GeoJsonGeometry | null {
	return Option.getOrNull(Schema.decodeUnknownOption(GeoJsonGeometry)(value));
}

export function decodeDetections(value: unknown): ReadonlyArray<FireDetection> {
	return Option.getOrElse(
		Schema.decodeUnknownOption(Schema.Array(FireDetection))(value),
		() => [],
	);
}

export function decodeLossYears(value: unknown): ReadonlyArray<LossYear> {
	return Option.getOrElse(
		Schema.decodeUnknownOption(Schema.Array(LossYear))(value),
		() => [],
	);
}

export function numberValue(value: unknown): number | null {
	return typeof value === "number" && Number.isFinite(value) ? value : null;
}

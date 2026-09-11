import { describe, expect, it } from "vitest";

import {
	decodeDetections,
	decodeGeometry,
	decodeLossYears,
	findEvidence,
	numberValue,
} from "./evidence";

describe("evidence decoders", () => {
	it("decodes a GeoJSON polygon", () => {
		const geometry = decodeGeometry({
			type: "Polygon",
			coordinates: [
				[
					[101, 0],
					[101.1, 0],
					[101.1, 0.1],
					[101, 0],
				],
			],
		});
		expect(geometry?.type).toBe("Polygon");
	});

	it("returns null for malformed geometry", () => {
		expect(decodeGeometry({ type: "Point", coordinates: [0, 0] })).toBeNull();
		expect(decodeGeometry(null)).toBeNull();
	});

	it("decodes FIRMS detections and drops malformed rows", () => {
		const detections = decodeDetections([
			{
				latitude: -1.2,
				longitude: 101.5,
				acq_date: "2026-09-01",
				frp: 12.5,
				confidence: "nominal",
			},
		]);
		expect(detections).toHaveLength(1);
		expect(detections[0]?.frp).toBe(12.5);
		expect(decodeDetections("not-a-list")).toEqual([]);
	});

	it("decodes loss-by-year rows", () => {
		const years = decodeLossYears([
			{ year: 2023, loss_ha: 12.5 },
			{ year: 2024, loss_ha: 0 },
		]);
		expect(years).toHaveLength(2);
		expect(years[0]?.year).toBe(2023);
	});

	it("finds evidence by claim", () => {
		const entry = {
			schema_version: 1,
			evidence_id: "EV-1",
			claim: "loss.total_loss_ha",
			value: 4,
			unit: "ha",
			source: "global_forest_watch",
			artifact: {},
			retrieved_at: null,
			cached: false,
			synthetic: false,
			disclosure: null,
		} as const;
		expect(findEvidence([entry], "loss.total_loss_ha")?.evidence_id).toBe(
			"EV-1",
		);
		expect(findEvidence([entry], "missing")).toBeUndefined();
	});

	it("narrows numeric values", () => {
		expect(numberValue(12)).toBe(12);
		expect(numberValue("12")).toBeNull();
		expect(numberValue(Number.NaN)).toBeNull();
	});
});

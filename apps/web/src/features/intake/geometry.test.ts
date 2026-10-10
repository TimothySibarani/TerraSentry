import { describe, expect, it } from "vitest";

import { parseGeometryText, vertexCount } from "./geometry";

const square = {
	type: "Polygon",
	coordinates: [
		[
			[101, 0.5],
			[101.02, 0.5],
			[101.02, 0.52],
			[101, 0.52],
			[101, 0.5],
		],
	],
};

describe("parseGeometryText", () => {
	it("accepts a GeoJSON polygon, Feature, and single-feature collection", () => {
		for (const value of [
			square,
			{ type: "Feature", properties: {}, geometry: square },
			{
				type: "FeatureCollection",
				features: [{ type: "Feature", properties: {}, geometry: square }],
			},
		]) {
			const result = parseGeometryText(JSON.stringify(value));
			expect(result.ok).toBe(true);
			if (result.ok) {
				expect(result.geometry.type).toBe("Polygon");
				expect(vertexCount(result.geometry)).toBe(5);
			}
		}
	});

	it("turns Google Maps lat, lon lines into a closed lon/lat polygon", () => {
		const result = parseGeometryText(
			"0.7431, 101.8612\n0.7398, 101.8905\n0.7187, 101.8963",
		);
		expect(result.ok).toBe(true);
		if (result.ok && result.geometry.type === "Polygon") {
			const ring = result.geometry.coordinates[0] ?? [];
			expect(ring[0]).toEqual([101.8612, 0.7431]);
			expect(ring.at(-1)).toEqual(ring[0]);
			expect(ring).toHaveLength(4);
		}
	});

	it("treats a single coordinate line as a point", () => {
		const result = parseGeometryText("0.73, 101.87");
		expect(result.ok && result.geometry).toEqual({
			type: "Point",
			coordinates: [101.87, 0.73],
		});
	});

	it("explains what is wrong", () => {
		expect(parseGeometryText("")).toMatchObject({ ok: false });
		expect(parseGeometryText("{not json")).toEqual({
			ok: false,
			message: "this is not valid JSON",
		});
		expect(parseGeometryText("0.7, 101.8\nhello")).toMatchObject({
			ok: false,
			message: expect.stringContaining("line 2"),
		});
		expect(
			parseGeometryText(
				JSON.stringify({
					type: "LineString",
					coordinates: [
						[0, 0],
						[1, 1],
					],
				}),
			),
		).toMatchObject({ ok: false });
		expect(
			parseGeometryText(
				JSON.stringify({ type: "FeatureCollection", features: [{}, {}] }),
			),
		).toMatchObject({
			ok: false,
			message: expect.stringContaining("2 features"),
		});
		// lat/lon swapped in GeoJSON puts latitude out of range.
		expect(
			parseGeometryText(
				JSON.stringify({ type: "Point", coordinates: [0.5, 101] }),
			),
		).toMatchObject({ ok: false, message: expect.stringContaining("WGS84") });
	});
});

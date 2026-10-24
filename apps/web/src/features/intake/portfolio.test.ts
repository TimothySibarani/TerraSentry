import { describe, expect, it } from "vitest";

import { PORTFOLIO_MAX_ROWS, previewPortfolio } from "./portfolio";

const HEADER =
	"country,label,wkt,legal_name,commodity,description,net_weight_kg,harvest_year";

describe("previewPortfolio (csv)", () => {
	it("counts rows and finds no problems in a complete file", () => {
		const csv = `${HEADER}\nID,A,"POLYGON((0 0,1 0,1 1,0 0))",PT A,wood,Pulp,1000,2026\n`;
		expect(previewPortfolio("suppliers.csv", csv)).toEqual({
			kind: "csv",
			rows: 1,
			problems: [],
		});
	});

	it("names each missing column and the missing plot location", () => {
		const preview = previewPortfolio("s.csv", "country,label\nID,A\n");
		expect(preview.problems).toContain("Missing column: legal_name");
		expect(preview.problems).toContain("Missing column: harvest_year");
		expect(preview.problems.join(" ")).toContain("wkt column, or lat and lon");
	});

	it("accepts supplier as the legal_name alias, lat/lon, semicolons and a BOM", () => {
		const csv =
			"﻿country;supplier;commodity;description;net_weight_kg;harvest_year;lat;lon\nID;PT A;wood;x;1;2026;0.1;101.2\n";
		expect(previewPortfolio("s.csv", csv).problems).toEqual([]);
	});

	it("flags an empty file, a header without rows and too many rows", () => {
		expect(previewPortfolio("s.csv", "").problems).toEqual([
			"The file is empty.",
		]);
		expect(previewPortfolio("s.csv", `${HEADER}\n`).problems).toContain(
			"The file has a header but no rows.",
		);
		const many = `${HEADER}\n${"ID,A,x,B,wood,d,1,2026\n".repeat(PORTFOLIO_MAX_ROWS + 1)}`;
		expect(previewPortfolio("s.csv", many).problems.join(" ")).toContain(
			`at most ${PORTFOLIO_MAX_ROWS}`,
		);
	});
});

describe("previewPortfolio (geojson)", () => {
	it("counts the features of a FeatureCollection", () => {
		const json = JSON.stringify({
			type: "FeatureCollection",
			features: [{}, {}],
		});
		expect(previewPortfolio("p.geojson", json)).toEqual({
			kind: "geojson",
			rows: 2,
			problems: [],
		});
	});

	it("rejects invalid JSON and anything but a FeatureCollection", () => {
		expect(previewPortfolio("p.geojson", "{nope").problems).toEqual([
			"The file is not valid JSON.",
		]);
		expect(
			previewPortfolio("p.json", JSON.stringify({ type: "Feature" })).problems,
		).toEqual(["GeoJSON import needs a FeatureCollection."]);
	});
});

it("rejects other file types", () => {
	expect(previewPortfolio("p.xlsx", "").kind).toBe("unsupported");
});

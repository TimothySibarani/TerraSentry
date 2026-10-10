import { describe, expect, it } from "vitest";

import {
	initialForm,
	issuesToErrors,
	SAMPLE_PLOT,
	stepOfField,
	toSubmission,
	validateStep,
} from "./form";

const complete = {
	...initialForm(),
	country: "ID",
	shape: SAMPLE_PLOT,
	label: "Blok 7",
	legalName: "PT Contoh",
	permitNumber: "12/HGU/BPN/2019",
	netWeightKg: "25,000",
	harvestYear: "2026",
};

describe("intake form", () => {
	it("blocks each step on its own required fields", () => {
		const empty = initialForm();
		expect(Object.keys(validateStep("plot", empty))).toEqual([
			"plot.country",
			"plot.geometry",
			"plot.label",
		]);
		expect(Object.keys(validateStep("supplier", empty))).toEqual([
			"supplier.legal_name",
		]);
		expect(Object.keys(validateStep("legality", empty))).toEqual([
			"legality.permit_number",
		]);
		expect(Object.keys(validateStep("consignment", empty))).toEqual([
			"consignment.net_weight_kg",
		]);
		for (const step of [
			"plot",
			"supplier",
			"legality",
			"consignment",
		] as const) {
			expect(validateStep(step, complete)).toEqual({});
		}
	});

	it("enforces the EUDR 4 ha limit for point plots", () => {
		const point = {
			...complete,
			plotMethod: "point" as const,
			pointLat: "0.73",
			pointLon: "101.87",
			declaredAreaHa: "6",
		};
		expect(validateStep("plot", point)["plot.declared_area_ha"]).toContain(
			"4 ha",
		);
		expect(validateStep("plot", { ...point, declaredAreaHa: "3.5" })).toEqual(
			{},
		);
	});

	it("builds the API submission", () => {
		const submission = toSubmission({
			...complete,
			certifications: ["ISPO"],
			owners: "A\nB",
		});
		expect(submission.plot.geometry).toEqual(SAMPLE_PLOT);
		expect(submission.plot.declared_area_ha).toBeNull();
		expect(submission.consignment.net_weight_kg).toBe(25000);
		expect(submission.supplier.beneficial_owners).toEqual(["A", "B"]);
		expect(submission.legality?.permit_type).toBe("hgu");
		const noPermit = toSubmission({ ...complete, permitType: "none" });
		expect(noPermit.legality).toMatchObject({
			permit_number: "",
			permit_status: "none",
		});
	});

	it("routes server issues to their step", () => {
		expect(stepOfField("plot.geometry")).toBe("plot");
		expect(stepOfField("consignment.hs_heading")).toBe("consignment");
		expect(stepOfField("file")).toBe("review");
		expect(
			issuesToErrors([
				{ field: "plot.geometry", message: "Self-intersection" },
			]),
		).toEqual({ "plot.geometry": "Self-intersection" });
	});
});

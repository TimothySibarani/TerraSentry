import { describe, expect, it } from "vitest";

import { contradictsRubric, noteRequired, sapEffect } from "./decision";

describe("sapEffect", () => {
	it("names the vendor change in auto mode", () => {
		expect(sapEffect("override")).toContain("vendor blocked");
		expect(sapEffect("approve")).toContain("vendor set to approved");
	});

	it("says the change waits for confirmation in confirm mode", () => {
		expect(sapEffect("override", "confirm")).toContain("once you confirm");
	});

	it("says SAP is untouched in off mode", () => {
		expect(sapEffect("approve", "off")).toContain("not touched");
	});
});

describe("note requirement", () => {
	it("is needed only when approving a high-risk supplier", () => {
		expect(contradictsRubric("high_risk", "approve")).toBe(true);
		expect(contradictsRubric("high_risk", "override")).toBe(false);
		expect(contradictsRubric("ambiguous", "approve")).toBe(false);
		expect(contradictsRubric(null, "approve")).toBe(false);
	});

	it("applies to a bulk selection when any run contradicts the rubric", () => {
		expect(noteRequired(["ambiguous", "high_risk"], "approve")).toBe(true);
		expect(noteRequired(["ambiguous", "ambiguous"], "approve")).toBe(false);
		expect(noteRequired(["high_risk"], "override")).toBe(false);
	});
});

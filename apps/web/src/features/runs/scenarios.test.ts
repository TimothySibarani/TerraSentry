import { expect, it } from "vitest";
import { DEMO_SCENARIOS, scenariosFor } from "./scenarios";

it("offers the fault-injection catch only for the scripted model", () => {
	const ids = (model: "scripted" | "bedrock") =>
		scenariosFor(model).map((scenario) => scenario.id);
	expect(ids("scripted")).toEqual([
		"compliant_live",
		"high_risk_live",
		"coverage_catch",
	]);
	expect(ids("bedrock")).toEqual(["compliant_live", "high_risk_live"]);
});

it("labels the verifier catch as fault injection", () => {
	const catchScenario = DEMO_SCENARIOS.find((s) => s.id === "coverage_catch");
	expect(catchScenario?.faultInjection).toBe(true);
	expect(catchScenario?.models).toEqual(["scripted"]);
});

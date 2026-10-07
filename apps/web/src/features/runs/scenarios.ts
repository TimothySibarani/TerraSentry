import type { ModelMode } from "@terrasentry/api-client";

export interface DemoScenario {
	id: string;
	label: string;
	description: string;
	/** Models this scenario can run on; omitted means every model. */
	models?: ReadonlyArray<ModelMode>;
	/** Scripted-only scenario that deliberately breaks the agent to show a gate working. */
	faultInjection?: boolean;
}

/**
 * The PRD demo scenarios plus the verifier-catch fault scenario. There is no
 * scenario catalog endpoint; the names come from `data/seed/demo_polygons.json`
 * (`scenario` field) and the server's `FAULT_SCENARIOS`.
 */
export const DEMO_SCENARIOS: ReadonlyArray<DemoScenario> = [
	{
		id: "compliant_live",
		label: "Compliant scenario",
		description:
			"Clean parcel: geospatial, thermal and legality screening find nothing to chase, so the Supervisor does not re-task anyone. The verifier confirms and a DDS is released.",
	},
	{
		id: "high_risk_live",
		label: "High-risk scenario",
		description:
			"Riau peat plot: screening raises signals, so the Supervisor re-tasks the legality and geospatial analysts for a deep dive and the trace shows each reason. The rubric still owns the verdict, the verifier re-derives every metric, and the vendor is blocked in SAP (stub).",
	},
	{
		id: "coverage_catch",
		label: "Verifier catch",
		description:
			"The scripted Supervisor skips the required deep dive on the high-risk plot. The verifier's coverage check rejects the run, so no DDS is released.",
		models: ["scripted"],
		faultInjection: true,
	},
];

export function scenariosFor(model: ModelMode): ReadonlyArray<DemoScenario> {
	return DEMO_SCENARIOS.filter(
		(scenario) =>
			scenario.models === undefined || scenario.models.includes(model),
	);
}

export interface DemoScenario {
	id: string;
	label: string;
	description: string;
}

/**
 * The two PRD demo scenarios. There is no scenario catalog endpoint; the
 * names come from `data/seed/demo_polygons.json` (`scenario` field).
 */
export const DEMO_SCENARIOS: ReadonlyArray<DemoScenario> = [
	{
		id: "compliant_live",
		label: "Compliant scenario",
		description:
			"Clean parcel: geospatial and thermal checks pass, the verifier confirms, and a DDS is released.",
	},
	{
		id: "high_risk_live",
		label: "High-risk scenario",
		description:
			"Permit and satellite signals conflict: the supervisor re-tasks the legality agent and the verifier challenges the draft.",
	},
];

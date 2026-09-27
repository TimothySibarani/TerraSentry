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
			"Riau peat plot with a suspended (synthetic) permit: the rubric flags high risk from the permit status alongside real GFW and FIRMS evidence, the verifier re-derives every metric, and the vendor is blocked in SAP (stub).",
	},
];

import type {
	EvidenceEntry,
	VerdictOut,
	VerificationReport,
} from "@terrasentry/api-client";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { AssessmentPanel } from "./assessment-panel";
import { EvidenceTable } from "./evidence-table";

afterEach(cleanup);

it("explains critical findings and links to the named source evidence", () => {
	const verdict: VerdictOut = {
		record_id: "REC-1",
		supplier_id: "SUP-1",
		polygon_id: "PLY-1",
		run_state: "complete",
		assessment: {
			assessment_date: "2026-10-02",
			record_id: "REC-1",
			supplier_id: "SUP-1",
			polygon_id: "PLY-1",
			rubric_version: "1.1.0",
			score: 60,
			verdict: "high_risk",
			risk_level: "non_negligible",
			citations: {},
			disclosures: [],
			data_gaps: [],
			findings: [
				{
					code: "protected_area",
					level: "flag",
					points: 60,
					detail: "Protected-area overlap: Tanjung Puting (30.73 ha).",
					metrics: { overlap_ha: 30.73 },
					evidence_ids: ["EV-wdpa"],
					mitigating: false,
				},
			],
		},
		fingerprint: "test",
		expected_archetype: null,
		expected_signal: null,
		expected_ambiguity: null,
		pending: false,
	};
	render(
		<AssessmentPanel
			runId="run-1"
			verdict={verdict}
			verification={null}
			disclosures={[]}
		/>,
	);
	expect(screen.getByText("Why this verdict?")).toBeDefined();
	expect(
		screen.getByRole("link", { name: "EV-wdpa" }).getAttribute("href"),
	).toBe("/runs/run-1?tab=evidence#EV-wdpa");
	expect(screen.getByText("Unlabelled submitted record")).toBeDefined();
});

it("keeps full named feature artifacts and legacy provenance readable at evidence anchors", () => {
	const entry: EvidenceEntry = {
		schema_version: 2,
		evidence_id: "EV-wdpa",
		claim: "context.protected_areas",
		value: {
			features: [{ name: "Tanjung Puting", company: "Declared holder" }],
			overlap_ha: 30.73,
		},
		unit: "ha",
		source: "global_forest_watch",
		artifact: { dataset: "wdpa_protected_areas", version: "v202512" },
		retrieved_at: null,
		cached: false,
		synthetic: false,
		disclosure: null,
	};
	render(<EvidenceTable entries={[entry]} />);
	expect(document.getElementById("EV-wdpa")?.textContent).toBe(
		"context.protected_areas",
	);
	expect(screen.getByText("Legacy provenance unknown")).toBeDefined();
	const detail = document.querySelector("details pre")?.textContent ?? "";
	expect(detail).toContain("Tanjung Puting");
	expect(detail).toContain("wdpa_protected_areas");
	expect(detail).toContain("Declared holder");
});

const coverageReport = (
	severity: "error" | "info",
	accepted: boolean,
): VerificationReport => ({
	accepted,
	checked_claims: ["coverage.get_context_layers"],
	notes: [],
	llm_reviewed: false,
	model_id: null,
	challenges: [
		{
			kind: "coverage",
			severity,
			detail:
				severity === "error"
					? "required tool get_context_layers was not called (required by findings: protected_area)"
					: "get_context_layers was attempted but its sources were unavailable; data gap",
			source: "trace",
			evidence_ids: [],
			expected: "polygon_id=PLY-001",
			observed:
				severity === "error"
					? "no matching tool step recorded"
					: "attempted; status=error",
		},
	],
});

it("labels a missing deep dive as a coverage error", () => {
	render(
		<AssessmentPanel
			runId="run-1"
			verdict={null}
			verification={coverageReport("error", false)}
			disclosures={[]}
		/>,
	);
	expect(screen.getByText("Missing deep dive")).toBeDefined();
	expect(screen.getByText("Rejected")).toBeDefined();
	expect(screen.getByText(/get_context_layers was not called/)).toBeDefined();
	expect(
		screen.getByText(/expected=polygon_id=PLY-001 · observed=/),
	).toBeDefined();
});

it("shows an attempted-but-failed deep dive as an info data gap", () => {
	render(
		<AssessmentPanel
			runId="run-1"
			verdict={null}
			verification={coverageReport("info", true)}
			disclosures={[]}
		/>,
	);
	expect(screen.getByText("Attempted, data gap")).toBeDefined();
	expect(screen.getByText("info")).toBeDefined();
	expect(screen.getByText("Accepted")).toBeDefined();
});

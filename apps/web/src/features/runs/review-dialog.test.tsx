import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewDialog, topFindings } from "./review-dialog";

const decide = vi.hoisted(() => vi.fn());
vi.mock("#/features/runs/mutations", () => ({
	useRunDecision: () => ({
		mutateAsync: decide,
		isPending: false,
		error: null,
	}),
}));

beforeEach(() => decide.mockReset().mockResolvedValue({}));
afterEach(cleanup);

const findings = [
	{ code: "fire_cluster", level: "clear", detail: "No fires." },
	{ code: "legal_permit", level: "borderline", detail: "Permit gap." },
	{ code: "protected_area", level: "flag", detail: "Overlaps a reserve." },
];

function open(props: Partial<Parameters<typeof ReviewDialog>[0]> = {}) {
	render(<ReviewDialog runId="run-1" verdict="ambiguous" {...props} />);
	fireEvent.click(screen.getByRole("button", { name: "Review and decide" }));
}

describe("topFindings", () => {
	it("lists flags before borderlines, drops clear findings and caps the list", () => {
		expect(topFindings(findings).map((finding) => finding.code)).toEqual([
			"protected_area",
			"legal_permit",
		]);
		expect(topFindings(findings, 1)).toHaveLength(1);
	});
});

describe("ReviewDialog", () => {
	it("shows the brief and the SAP effect of each choice before anything is decided", () => {
		open({ brief: "Plot overlaps a reserve.", findings });
		expect(screen.getByText(/Plot overlaps a reserve\./)).toBeDefined();
		expect(screen.getByText("Overlaps a reserve.")).toBeDefined();
		expect(
			screen.getByText(/vendor blocked, purchasing block set/),
		).toBeDefined();
		expect(screen.getByText(/vendor set to approved/)).toBeDefined();
	});

	it("makes an ambiguous run choose explicitly", () => {
		open();
		const submit = screen.getByRole("button", { name: "Choose a decision" });
		expect((submit as HTMLButtonElement).disabled).toBe(true);
	});

	it("preselects blocking for a high-risk run and records it without a note", async () => {
		open({ verdict: "high_risk" });
		fireEvent.click(screen.getByRole("button", { name: "Block supplier" }));
		await waitFor(() => expect(decide).toHaveBeenCalledTimes(1));
		expect(decide).toHaveBeenCalledWith({
			decision: "override",
			reviewer: "demo-reviewer",
			note: "",
		});
	});

	it("requires a reason before approving a high-risk supplier", async () => {
		open({ verdict: "high_risk" });
		fireEvent.click(screen.getByRole("radio", { name: /Approve supplier/ }));
		const submit = screen.getByRole("button", { name: "Approve supplier" });
		expect((submit as HTMLButtonElement).disabled).toBe(true);
		expect(screen.getByText(/overrides the rubric/)).toBeDefined();

		fireEvent.change(screen.getByLabelText(/Note/), {
			target: { value: "Renewal evidence attached" },
		});
		expect((submit as HTMLButtonElement).disabled).toBe(false);
		fireEvent.click(submit);
		await waitFor(() => expect(decide).toHaveBeenCalledTimes(1));
		expect(decide).toHaveBeenCalledWith({
			decision: "approve",
			reviewer: "demo-reviewer",
			note: "Renewal evidence attached",
		});
	});

	it("says SAP stays untouched when the run was started with the ERP off", () => {
		open({ erpMode: "off" });
		expect(screen.getAllByText(/SAP is not touched/)).toHaveLength(2);
	});

	it("renders markdown properly in the agent brief without raw markdown tokens", () => {
		open({
			brief:
				"Both deep dives are complete.\n\n## Summary\n- **Deforestation** detected",
		});
		expect(screen.getByText("Both deep dives are complete.")).toBeDefined();
		expect(screen.getByRole("heading", { name: "Summary" })).toBeDefined();
		expect(screen.getByText("Deforestation")).toBeDefined();
	});
});

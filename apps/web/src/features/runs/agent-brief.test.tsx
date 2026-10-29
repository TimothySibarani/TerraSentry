import type { TraceStep } from "@terrasentry/api-client";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DateTime } from "effect";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentBrief, specialistReports } from "./agent-brief";

afterEach(cleanup);

const at = DateTime.fromDateUnsafe(new Date("2026-10-13T10:00:00Z"));

const step = (id: string, kind: TraceStep["kind"]): TraceStep => ({
	step_id: id,
	kind,
	name: "geospatial_analyst",
	detail: "",
	at,
	payload: {},
});

describe("AgentBrief", () => {
	it("shows the written summary as context, never as the verdict", () => {
		render(
			<AgentBrief
				summary="Loss found; permit expired."
				model="sap"
				steps={[step("STEP-001", "report"), step("STEP-002", "report")]}
			/>,
		);
		expect(screen.getByText("Agent brief")).toBeDefined();
		expect(screen.getByText("Loss found; permit expired.")).toBeDefined();
		expect(screen.getByText(/the rubric decides the verdict/)).toBeDefined();
		expect(screen.getByText("2 specialist reports in the trace")).toBeDefined();
	});

	it("admits when a scripted replay wrote the summary", () => {
		render(
			<AgentBrief summary="Evidence gathered." model="scripted" steps={[]} />,
		);
		expect(screen.getByText(/canned, not written by a model/)).toBeDefined();
	});

	it("renders nothing for screening runs or empty summaries", () => {
		const screening = render(
			<AgentBrief
				summary="high_risk score 70"
				model="deterministic"
				steps={[]}
			/>,
		);
		expect(screening.container.textContent).toBe("");
		cleanup();
		const empty = render(<AgentBrief summary="  " model="sap" steps={[]} />);
		expect(empty.container.textContent).toBe("");
	});

	it("renders markdown formatting in the agent brief summary", () => {
		render(
			<AgentBrief
				summary={"## Evidence Summary\n- **77.16 ha** loss detected"}
				model="sap"
				steps={[]}
			/>,
		);
		expect(
			screen.getByRole("heading", { level: 2, name: "Evidence Summary" }),
		).toBeDefined();
		expect(screen.getByText("77.16 ha")).toBeDefined();
	});

	it("toggles between technical brief and public summary with a breathing animation", () => {
		vi.useFakeTimers();
		render(
			<AgentBrief
				summary={"## Evidence Summary\n- **77.16 ha** loss detected on PLY-001"}
				model="sap"
				steps={[]}
			/>,
		);

		const button = screen.getByRole("button", { name: /simplify for public/i });
		expect(button).toBeDefined();

		// Click to trigger simplifying breathing state
		fireEvent.click(button);

		// Breathing animation and processing indicators are visible
		expect(screen.getByTestId("breathing-simplifying")).toBeDefined();
		expect(screen.getAllByText(/Simplifying…/i).length).toBeGreaterThanOrEqual(1);

		// Advance timer for breathing animation
		act(() => {
			vi.advanceTimersByTime(800);
		});

		expect(screen.getByText("Public view")).toBeDefined();
		expect(
			screen.getByText(/Public Summary: What You Need to Know/i),
		).toBeDefined();
		expect(screen.getByRole("button", { name: /technical brief/i })).toBeDefined();

		// Switch back to technical brief
		fireEvent.click(screen.getByRole("button", { name: /technical brief/i }));
		expect(
			screen.getByRole("heading", { level: 2, name: "Evidence Summary" }),
		).toBeDefined();
		vi.useRealTimers();
	});

	it("collects only report steps", () => {
		const steps = [step("STEP-001", "tool"), step("STEP-002", "report")];
		expect(specialistReports(steps).map((item) => item.step_id)).toEqual([
			"STEP-002",
		]);
	});
});

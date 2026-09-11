import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RiskLevelBadge, RunStateBadge, VerdictBadge } from "./status-badge";

describe("status badges", () => {
	it("renders run states with readable labels", () => {
		render(<RunStateBadge state="complete" />);
		expect(screen.getByText("Complete")).toBeDefined();
	});

	it("renders awaiting review as a review badge", () => {
		render(<RunStateBadge state="awaiting_review" />);
		expect(screen.getByText("Awaiting review")).toBeDefined();
	});

	it("renders verdicts and fallbacks", () => {
		render(<VerdictBadge verdict="high_risk" />);
		expect(screen.getByText("High risk")).toBeDefined();
		render(<VerdictBadge verdict={null} />);
		expect(screen.getByText("—")).toBeDefined();
	});

	it("renders risk levels", () => {
		render(<RiskLevelBadge level="non_negligible" />);
		expect(screen.getByText("Non-negligible")).toBeDefined();
	});
});

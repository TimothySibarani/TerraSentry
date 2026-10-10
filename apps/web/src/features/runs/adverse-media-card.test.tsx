import type { AdverseMediaReport } from "@terrasentry/api-client";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { AdverseMediaCard } from "./adverse-media-card";

afterEach(cleanup);

const report: AdverseMediaReport = {
	subject: "PT Sumber",
	country: "ID",
	status: "success",
	summary: "One simulated finding.",
	findings: [
		{
			claim: "Simulated dispute.",
			citations: [
				{
					url: "https://example.org/x",
					title: "Simulated source",
					published: null,
				},
			],
		},
	],
	model: "stub",
	synthetic: true,
	disclosure: "Simulated adverse-media result; no web search was performed.",
	cached: false,
	error: null,
};

it("shows cited findings with safe external links and the context-only label", () => {
	render(<AdverseMediaCard report={report} />);
	expect(screen.getByText("Context only, not scored")).toBeDefined();
	expect(screen.getByText("Simulated")).toBeDefined();
	const link = screen.getByRole("link", { name: "Simulated source" });
	expect(link.getAttribute("href")).toBe("https://example.org/x");
	expect(link.getAttribute("rel")).toContain("noopener");
	expect(screen.getByText(/no web search was performed/)).toBeDefined();
});

it("explains an unavailable search instead of showing findings", () => {
	render(
		<AdverseMediaCard
			report={{
				...report,
				status: "unavailable",
				findings: [],
				error: "timeout",
			}}
		/>,
	);
	expect(screen.getByText("Adverse media unavailable")).toBeDefined();
	expect(screen.getByText("timeout")).toBeDefined();
	expect(screen.queryByRole("link")).toBeNull();
});

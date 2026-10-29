import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Markdown } from "./markdown";

afterEach(cleanup);

describe("Markdown", () => {
	it("renders headings, paragraphs, and emphasis", () => {
		const content = `## Evidence Summary
This is a paragraph with **bold evidence** and *italic note*.`;

		render(<Markdown content={content} />);

		expect(
			screen.getByRole("heading", { level: 2, name: "Evidence Summary" }),
		).toBeDefined();
		expect(screen.getByText(/This is a paragraph with/)).toBeDefined();
		expect(screen.getByText("bold evidence")).toBeDefined();
		expect(screen.getByText("italic note")).toBeDefined();
	});

	it("renders GFM tables properly", () => {
		const content = `| Specialist | Dataset(s) | Version(s) |
|---|---|---|
| Geospatial Analyst | \`umd_tree_cover_loss\` | v1.13 |`;

		render(<Markdown content={content} />);

		expect(screen.getByRole("table")).toBeDefined();
		expect(screen.getByText("Specialist")).toBeDefined();
		expect(screen.getByText("Geospatial Analyst")).toBeDefined();
		expect(screen.getByText("umd_tree_cover_loss")).toBeDefined();
		expect(screen.getByText("v1.13")).toBeDefined();
	});

	it("renders bullet lists and code blocks", () => {
		const content = `- 77.16 ha of loss detected
- Concession overlap confirmed

\`\`\`
raw code block
\`\`\``;

		render(<Markdown content={content} />);

		expect(screen.getByText("77.16 ha of loss detected")).toBeDefined();
		expect(screen.getByText("Concession overlap confirmed")).toBeDefined();
		expect(screen.getByText("raw code block")).toBeDefined();
	});
});

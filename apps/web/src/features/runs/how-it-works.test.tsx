import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { HowItWorks } from "./how-it-works";
import { SOURCE_TOOLS } from "./pipeline";
import { layerTitle } from "./work-context";

afterEach(cleanup);

it("names every source tool and the datasets it is checked against", () => {
	render(<HowItWorks />);
	const tools = screen.getByRole("region", { name: "2 · Agents call tools" });
	for (const tool of SOURCE_TOOLS)
		expect(within(tools).getByText(tool.name)).toBeDefined();
	const checked = screen.getByRole("region", { name: "3 · Checked against" });
	expect(within(checked).getByText("NASA FIRMS VIIRS")).toBeDefined();
	expect(within(checked).getByText("WDPA protected areas")).toBeDefined();
});

it("covers every tool the dataset cards know about", () => {
	const names = new Set(SOURCE_TOOLS.map((tool) => tool.name));
	for (const name of [
		"get_tree_cover_loss",
		"get_fire_hotspots",
		"get_context_layers",
		"get_legality_record",
		"get_consignment",
		"check_concession_overlap",
	])
		expect(names.has(name), `${name} (${layerTitle(name)})`).toBe(true);
});

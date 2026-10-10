import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { BatchModeBadge, batchModeLabel, labelledNote } from "./batch-mode";

afterEach(cleanup);

it("labels what a batch actually ran", () => {
	expect(batchModeLabel("screening", null)).toBe("Fast screening");
	expect(batchModeLabel("agent", "bedrock")).toBe("Agent · bedrock");
	render(<BatchModeBadge mode="agent" model="bedrock" />);
	expect(screen.getByText("Agent · bedrock")).toBeDefined();
});

it("says how many unlabelled records the design match excludes", () => {
	expect(labelledNote(3)).toBe("Labelled records only · 3 unlabelled excluded");
	expect(labelledNote(0)).toBe("Labelled records only");
});

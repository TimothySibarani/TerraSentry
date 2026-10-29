import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { expectedLabel, RunInputPanel } from "./run-input";
import { highRiskRecord } from "./run-input.fixture";

vi.mock("#/components/map/map-view", () => ({
	MapView: () => <div data-testid="map-view" />,
}));

afterEach(cleanup);

it("shows every input section with its provenance and the declared permit", () => {
	render(
		<RunInputPanel
			record={highRiskRecord}
			model="sap"
			options={{ scenario: "high_risk_live", refresh: true, batch_mode: null }}
		/>,
	);
	const supplier = screen.getByRole("region", { name: "Supplier & permit" });
	expect(within(supplier).getByText("HGU No. 343/HGU/BPN/2020")).toBeDefined();
	expect(within(supplier).getByText("suspended")).toBeDefined();
	expect(within(supplier).getByText("Synthetic")).toBeDefined();
	expect(screen.getByTestId("map-view")).toBeDefined();
	expect(screen.getByText("Refreshed from sources")).toBeDefined();
	expect(screen.getByText("high risk · legal")).toBeDefined();
});

it("compact mode drops the map, operator and settings", () => {
	render(<RunInputPanel record={highRiskRecord} compact />);
	expect(screen.queryByTestId("map-view")).toBeNull();
	expect(screen.queryByRole("region", { name: "Run settings" })).toBeNull();
	expect(screen.getByText("48,687 t")).toBeDefined();
});

it("says when launch options were not recorded", () => {
	render(
		<RunInputPanel record={highRiskRecord} model="scripted" options={{}} />,
	);
	expect(screen.getByText("Not recorded")).toBeDefined();
});

it("labels the design target only for seeded records", () => {
	expect(expectedLabel(highRiskRecord)).toBe("high risk · legal");
	expect(
		expectedLabel({ ...highRiskRecord, expected_archetype: null }),
	).toBeNull();
});

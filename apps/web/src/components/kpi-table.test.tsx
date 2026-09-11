import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { KpiTable } from "./kpi-table";

describe("KpiTable", () => {
	it("renders every metric with its target, measured value, and source", () => {
		render(
			<KpiTable
				rows={[
					{
						metric: "Batch wall clock",
						target: "Demo slot",
						value: "2m 3s",
						source: "batch-1",
					},
					{
						metric: "Design match",
						target: "100% exact",
						value: "100%",
						source: "Confusion diagonal",
					},
				]}
			/>,
		);
		expect(screen.getByText("Batch wall clock")).toBeDefined();
		expect(screen.getByText("2m 3s")).toBeDefined();
		expect(screen.getByText("100% exact")).toBeDefined();
		expect(screen.getByText("Confusion diagonal")).toBeDefined();
	});
});

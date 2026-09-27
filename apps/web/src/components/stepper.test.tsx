import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Stepper } from "./stepper";

describe("Stepper", () => {
	it("marks the current step, locks upcoming ones, and reports selection", () => {
		const onSelect = vi.fn();
		render(
			<Stepper
				label="Screening steps"
				onSelect={onSelect}
				steps={[
					{ id: "plot", title: "Plot", status: "complete" },
					{ id: "supplier", title: "Supplier", status: "current" },
					{ id: "review", title: "Review", status: "upcoming", disabled: true },
				]}
			/>,
		);
		const nav = screen.getByRole("navigation", { name: "Screening steps" });
		expect(nav).toBeDefined();
		const current = screen.getByRole("button", { name: /Supplier/ });
		expect(current.getAttribute("aria-current")).toBe("step");
		expect(
			screen.getByRole("button", { name: /Completed: Plot/ }),
		).toBeDefined();
		const locked = screen.getByRole("button", { name: /Review/ });
		expect((locked as HTMLButtonElement).disabled).toBe(true);
		fireEvent.click(screen.getByRole("button", { name: /Plot/ }));
		expect(onSelect).toHaveBeenCalledWith("plot");
	});
});

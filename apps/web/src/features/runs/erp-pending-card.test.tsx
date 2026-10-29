import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ErpPendingCard } from "./erp-pending-card";

const confirm = vi.hoisted(() => vi.fn());
vi.mock("#/features/runs/mutations", () => ({
	useConfirmErpAction: () => ({
		mutate: confirm,
		isPending: false,
		error: null,
	}),
}));

afterEach(() => {
	cleanup();
	confirm.mockReset();
});

describe("ErpPendingCard", () => {
	it("says nothing has changed and names the SAP effect of a block", () => {
		render(<ErpPendingCard runId="run-1" pending="blocked" />);
		expect(screen.getByText(/Nothing has been changed yet/)).toBeDefined();
		expect(
			screen.getByText(/block the vendor and set the purchasing block/),
		).toBeDefined();
		fireEvent.click(
			screen.getByRole("button", { name: "Block vendor in SAP" }),
		);
		expect(confirm).toHaveBeenCalledTimes(1);
	});

	it("offers to approve the vendor for an approved plan", () => {
		render(<ErpPendingCard runId="run-1" pending="approved" />);
		expect(
			screen.getByRole("button", { name: "Approve vendor in SAP" }),
		).toBeDefined();
	});
});

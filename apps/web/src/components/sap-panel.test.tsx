import type { SapActionOut, SupplierSapOut } from "@terrasentry/api-client";
import { cleanup, render, screen } from "@testing-library/react";
import { DateTime } from "effect";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
	SapActionCard,
	SapModeBadge,
	SapStatusBadge,
	SupplierSapCard,
} from "./sap-panel";

afterEach(cleanup);

vi.mock("@tanstack/react-router", () => ({
	Link: ({ children }: { children: ReactNode }) => (
		<a href="/runs/run-1">{children}</a>
	),
}));

const performedAt = DateTime.fromDateUnsafe(
	new Date("2026-09-11T10:00:00Z"),
);

const action: SapActionOut = {
	run_id: "run-1",
	supplier_id: "SUP-001",
	vendor_id: "SUP-001",
	mode: "stub",
	status: "blocked",
	purchasing_block: true,
	real: false,
	external_reference: null,
	error: null,
	performed_at: performedAt,
};

const supplierSap: SupplierSapOut = {
	vendor_id: "SUP-001",
	status: "blocked",
	purchasing_block: true,
	mode: "stub",
	real: false,
	disclosure: "SAP runs against a schema-accurate stub.",
	last_action: action,
};

describe("SAP badges", () => {
	it("labels approved, blocked, and failed actions", () => {
		render(<SapStatusBadge status="approved" />);
		expect(screen.getByText("Approved")).toBeDefined();
		render(<SapStatusBadge status="blocked" />);
		expect(screen.getByText("Blocked")).toBeDefined();
		render(<SapStatusBadge status="failed" />);
		expect(screen.getByText("Failed")).toBeDefined();
	});

	it("distinguishes the stub from a real endpoint", () => {
		render(<SapModeBadge mode="stub" real={false} />);
		expect(screen.getByText(/SAP stub/)).toBeDefined();
		render(<SapModeBadge mode="sandbox" real={true} />);
		expect(screen.getByText(/hosted endpoint/)).toBeDefined();
	});
});

describe("SapActionCard", () => {
	it("renders the recorded vendor action", () => {
		render(<SapActionCard action={action} />);
		expect(screen.getByText("ERP action (SAP)")).toBeDefined();
		expect(screen.getByText(/Vendor SUP-001 reached blocked/)).toBeDefined();
		expect(screen.getByText("Set")).toBeDefined();
	});

	it("explains the withheld state before a human decision", () => {
		render(<SapActionCard action={null} />);
		expect(screen.getByText(/No ERP action recorded yet/)).toBeDefined();
	});

	it("surfaces a failed ERP call without hiding the verdict", () => {
		render(
			<SapActionCard
				action={{ ...action, status: "failed", error: "IntegrationError: down" }}
			/>,
		);
		expect(screen.getByText("Failed")).toBeDefined();
		expect(screen.getByText(/IntegrationError: down/)).toBeDefined();
	});
});

describe("SupplierSapCard", () => {
	it("renders the current vendor state and disclosure", () => {
		render(<SupplierSapCard sap={supplierSap} />);
		expect(screen.getByText("ERP vendor status")).toBeDefined();
		expect(
			screen.getByText("SAP runs against a schema-accurate stub."),
		).toBeDefined();
		expect(screen.getByText("SUP-001")).toBeDefined();
		expect(screen.getByText(/blocked ·/)).toBeDefined();
	});

	it("renders nothing without a supplier SAP payload", () => {
		const { container } = render(<SupplierSapCard sap={null} />);
		expect(container.firstChild).toBeNull();
	});
});

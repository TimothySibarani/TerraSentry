import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	ApiClientError,
	type OperatorSettingOut,
} from "@terrasentry/api-client";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProvenanceBadge } from "#/components/provenance-badge";
import { OperatorForm } from "#/routes/settings";

const api = vi.hoisted(() => ({ updateOperator: vi.fn() }));
vi.mock("#/lib/api", () => ({
	runApi: (fn: (client: typeof api) => unknown) => fn(api),
}));
afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});
const initial: OperatorSettingOut = {
	configured: false,
	updated_at: null,
	profile: {
		operator_id: "OP-TEST",
		legal_name: "Demo Importer",
		identifier_type: "eori",
		identifier_value: "NL12345",
		address_line: "Port 1",
		postal_code: "1234",
		city: "Port",
		country: "NL",
		email: "test@example.org",
		phone: "+31123",
		activity_type: "IMPORT",
		country_of_activity: "NL",
		border_cross_country: "NL",
		provenance: "synthetic",
		synthetic: true,
		disclosure: "Synthetic test fixture",
	},
};

it("keeps dirty fields on refetch and saves only editable fields into the query cache", async () => {
	const client = new QueryClient({
		defaultOptions: { mutations: { retry: false } },
	});
	const view = (value: OperatorSettingOut) => (
		<QueryClientProvider client={client}>
			<OperatorForm initial={value} />
		</QueryClientProvider>
	);
	const rendered = render(view(initial));
	fireEvent.change(screen.getByLabelText(/Legal name/), {
		target: { value: "My importer" },
	});
	rendered.rerender(
		view({
			...initial,
			profile: { ...initial.profile, legal_name: "Refetched name" },
		}),
	);
	expect((screen.getByLabelText(/Legal name/) as HTMLInputElement).value).toBe(
		"My importer",
	);
	const saved = {
		...initial,
		configured: true,
		profile: {
			...initial.profile,
			legal_name: "My importer",
			provenance: "operator_configured",
			synthetic: false,
		},
	};
	api.updateOperator.mockResolvedValue(saved);
	fireEvent.click(screen.getByText("Save operator profile"));
	await waitFor(() =>
		expect(screen.getByText("Operator profile saved.")).toBeDefined(),
	);
	expect(api.updateOperator.mock.calls[0]?.[0]).not.toHaveProperty("synthetic");
	expect(client.getQueryData(["settings", "operator"])).toEqual(saved);
});

it("maps rejected operator fields without erasing the draft", async () => {
	const client = new QueryClient({
		defaultOptions: { mutations: { retry: false } },
	});
	api.updateOperator.mockRejectedValue(
		new ApiClientError({
			operation: "updateOperator",
			status: 422,
			cause: "invalid",
			issues: [{ field: "identifier_value", message: "Invalid EORI" }],
		}),
	);
	render(
		<QueryClientProvider client={client}>
			<OperatorForm initial={initial} />
		</QueryClientProvider>,
	);
	fireEvent.click(screen.getByText("Save operator profile"));
	await waitFor(() => expect(screen.getByText("Invalid EORI")).toBeDefined());
	expect((screen.getByLabelText(/EORI/) as HTMLInputElement).value).toBe(
		"NL12345",
	);
});

it("labels all provenance classes and historical unknowns", () => {
	render(
		[
			"synthetic",
			"supplier_declared",
			"document_extracted",
			"sap_import",
			"real_source",
			"operator_configured",
			"derived",
			"legacy_unknown",
		].map((provenance) => (
			<ProvenanceBadge key={provenance} provenance={provenance} />
		)),
	);
	for (const label of [
		"Synthetic",
		"Supplier declared",
		"Document extracted",
		"SAP imported",
		"Source observation",
		"Operator configured",
		"Derived",
		"Legacy provenance unknown",
	])
		expect(screen.getByText(label)).toBeDefined();
});

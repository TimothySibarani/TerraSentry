import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { RunLauncher } from "./launcher";

const health = vi.hoisted(() => vi.fn());
vi.mock("#/features/health/queries", () => ({
	healthQuery: () => ({ queryKey: ["health"], queryFn: health }),
}));
vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }));
vi.mock("#/features/runs/queries", async () => {
	const { highRiskRecord } = await import("./run-input.fixture");
	const all = [
		{ id: "compliant_live", label: "Compliant scenario", fault: false },
		{ id: "high_risk_live", label: "High-risk scenario", fault: false },
		{ id: "coverage_catch", label: "Verifier catch", fault: true },
	];
	return {
		scenariosQuery: (model: string) => ({
			queryKey: ["scenarios", model],
			queryFn: async () =>
				all
					.filter((item) => !item.fault || model === "scripted")
					.map((item) => ({
						id: item.id,
						label: item.label,
						description: `${item.label} description`,
						fault_injection: item.fault,
						models: item.fault ? ["scripted"] : null,
						record: highRiskRecord,
					})),
		}),
	};
});
const createBatch = vi.hoisted(() => vi.fn());
vi.mock("#/features/runs/mutations", () => ({
	useCreateRun: () => ({ mutate: vi.fn(), isPending: false, error: null }),
	useCreateBatch: () => ({
		mutate: createBatch,
		isPending: false,
		error: null,
	}),
}));

afterEach(cleanup);

function renderLauncher(props: { showScenarios?: boolean } = {}) {
	const client = new QueryClient();
	render(
		<QueryClientProvider client={client}>
			<RunLauncher {...props} />
		</QueryClientProvider>,
	);
	return client;
}

it("offers the labelled fault-injection scenario on the scripted model", async () => {
	health.mockResolvedValue({
		aicoreConfigured: false,
		defaultModel: "scripted",
	});
	const client = renderLauncher();
	await waitFor(() => expect(client.getQueryData(["health"])).toBeDefined());
	expect(
		await screen.findByRole("button", { name: /Verifier catch/ }),
	).toBeDefined();
	expect(screen.getAllByText("Fault injection").length).toBeGreaterThan(0);
	// Each scenario previews what it submits before it runs.
	expect(screen.getAllByText(/PLY-001 · Riau peat forests/).length).toBe(3);
	expect(screen.getAllByText("Expected: high risk · legal").length).toBe(3);
});

it("hides the fault-injection scenario when SAP AI Core is selected", async () => {
	health.mockResolvedValue({
		aicoreConfigured: true,
		defaultModel: "sap",
	});
	const client = renderLauncher();
	await waitFor(() => expect(client.getQueryData(["health"])).toBeDefined());
	await waitFor(() =>
		expect(screen.queryByRole("button", { name: /Verifier catch/ })).toBeNull(),
	);
	expect(
		await screen.findByRole("button", { name: /High-risk scenario/ }),
	).toBeDefined();
});

it("starts a screening batch without a model by default", async () => {
	health.mockResolvedValue({
		aicoreConfigured: false,
		defaultModel: "scripted",
	});
	createBatch.mockClear();
	const client = renderLauncher({ showScenarios: false });
	await waitFor(() => expect(client.getQueryData(["health"])).toBeDefined());
	fireEvent.click(
		screen.getByRole("button", { name: "Run 50-record screening" }),
	);
	expect(createBatch.mock.calls[0]?.[0]).toEqual({
		size: 50,
		refresh: false,
		mode: "screening",
	});
	expect(screen.getByText("Screening uses no model.")).toBeDefined();
});

it("sends the selected model for an agent batch and enables the picker", async () => {
	health.mockResolvedValue({
		aicoreConfigured: false,
		defaultModel: "scripted",
	});
	createBatch.mockClear();
	const client = renderLauncher({ showScenarios: false });
	await waitFor(() => expect(client.getQueryData(["health"])).toBeDefined());
	fireEvent.click(screen.getByRole("radio", { name: /Agent investigation/ }));
	expect(screen.queryByText("Screening uses no model.")).toBeNull();
	fireEvent.click(
		screen.getByRole("button", { name: "Run 50-record agent batch" }),
	);
	expect(createBatch.mock.calls[0]?.[0]).toEqual({
		size: 50,
		refresh: false,
		mode: "agent",
		model: "scripted",
	});
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { initialForm, SAMPLE_PLOT } from "./form";
import { useGeometryCheck, useScreenPlot } from "./queries";

const api = vi.hoisted(() => ({
	createRecord: vi.fn(),
	createRun: vi.fn(),
	validateGeometry: vi.fn(),
}));
vi.mock("#/lib/api", () => ({
	runApi: (fn: (client: typeof api) => unknown) => fn(api),
}));
afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});
function wrapper({ children }: { children: ReactNode }) {
	const client = new QueryClient({
		defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
	});
	return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

it("reuses a registered record after run failure and creates again for changed input", async () => {
	api.createRecord.mockResolvedValue({ record_id: "REC-U-1" });
	api.createRun
		.mockRejectedValueOnce(new Error("run unavailable"))
		.mockResolvedValue({ run_id: "run-1" });
	const form = {
		...initialForm(),
		shape: SAMPLE_PLOT,
		label: "Plot",
		legalName: "Supplier",
		netWeightKg: "10",
	};
	const { result } = renderHook(() => useScreenPlot(), { wrapper });
	await act(async () => {
		await expect(
			result.current.mutateAsync({ form, model: "scripted" }),
		).rejects.toThrow("unavailable");
	});
	await act(async () => {
		await result.current.mutateAsync({ form, model: "scripted" });
	});
	expect(api.createRecord).toHaveBeenCalledTimes(1);
	expect(api.createRun).toHaveBeenLastCalledWith({
		record_id: "REC-U-1",
		model: "scripted",
	});
	await act(async () => {
		await result.current.mutateAsync({
			form: { ...form, label: "Changed" },
			model: "scripted",
		});
	});
	expect(api.createRecord).toHaveBeenCalledTimes(2);
});

it("never approves edited geometry using the previous debounced result", async () => {
	api.validateGeometry.mockResolvedValue({ area_ha: 10 });
	const { result, rerender } = renderHook(
		({ geometry }) => useGeometryCheck(geometry, null),
		{ wrapper, initialProps: { geometry: SAMPLE_PLOT } },
	);
	await waitFor(() => expect(result.current.isCurrentValid).toBe(true));
	api.validateGeometry.mockRejectedValue(new Error("new plot rejected"));
	rerender({
		geometry: {
			type: "Polygon",
			coordinates: [
				[
					[0, 0],
					[1, 1],
					[1, 0],
					[0, 0],
				],
			],
		},
	});
	expect(result.current.isCurrentValid).toBe(false);
	expect(result.current.data).toBeUndefined();
	await waitFor(() => expect(result.current.error).not.toBeNull());
	expect(result.current.isCurrentValid).toBe(false);
});

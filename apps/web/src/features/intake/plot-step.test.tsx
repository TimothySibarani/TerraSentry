import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiClientError } from "@terrasentry/api-client";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type IntakeForm, initialForm } from "./form";
import { PlotStep } from "./plot-step";

const { validateGeometry } = vi.hoisted(() => ({ validateGeometry: vi.fn() }));

vi.mock("#/lib/api", () => ({
	runApi: (fn: (api: unknown) => unknown) => fn({ validateGeometry }),
}));

vi.mock("#/components/map/draw-map", () => ({
	DrawMap: () => <div data-testid="draw-map" />,
}));

vi.mock("#/components/map/map-view", () => ({
	MapView: () => <div data-testid="map-view" />,
}));

const SQUARE = {
	type: "Polygon",
	coordinates: [
		[
			[101.0, 0.5],
			[101.02, 0.5],
			[101.02, 0.52],
			[101.0, 0.52],
			[101.0, 0.5],
		],
	],
};

function report(area = 494.2) {
	return {
		geometry: SQUARE,
		query_geometry: SQUARE,
		geometry_type: "Polygon",
		area_ha: area,
		centroid_lat: 0.51,
		centroid_lon: 101.01,
		vertex_count: 5,
	};
}

function Harness({ initial }: { initial?: Partial<IntakeForm> }) {
	const [form, setForm] = useState<IntakeForm>({
		...initialForm(),
		...initial,
	});
	return (
		<PlotStep
			form={form}
			update={(patch) => setForm((current) => ({ ...current, ...patch }))}
			errors={{}}
		/>
	);
}

function renderStep(initial?: Partial<IntakeForm>) {
	const client = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	return render(
		<QueryClientProvider client={client}>
			<Harness initial={initial} />
		</QueryClientProvider>,
	);
}

afterEach(cleanup);

describe("PlotStep", () => {
	it("retains a MultiPolygon in Draw until replacement is explicit", () => {
		validateGeometry.mockResolvedValue(report());
		const shape = {
			type: "MultiPolygon" as const,
			coordinates: [SQUARE.coordinates],
		};
		renderStep({ shape });
		expect(screen.getByText("Boundary retained")).toBeDefined();
		expect(screen.getByTestId("map-view")).toBeDefined();
		expect(screen.queryByTestId("draw-map")).toBeNull();
		fireEvent.click(screen.getByText("Replace with a new polygon"));
		expect(screen.getByTestId("draw-map")).toBeDefined();
		expect(screen.queryByTestId("map-view")).toBeNull();
	});
	it("shows the server measurement for a pasted polygon", async () => {
		validateGeometry.mockResolvedValue(report());
		renderStep({ plotMethod: "paste" });

		fireEvent.change(screen.getByLabelText("Plot boundary"), {
			target: { value: JSON.stringify(SQUARE) },
		});

		await waitFor(() => expect(screen.getByText("494.2 ha")).toBeDefined());
		expect(screen.getByText("Valid")).toBeDefined();
		await waitFor(() =>
			expect(validateGeometry).toHaveBeenCalledWith({
				geometry: SQUARE,
				declared_area_ha: null,
			}),
		);
	});

	it("reports unparsable paste text without calling the server", async () => {
		validateGeometry.mockClear();
		renderStep({ plotMethod: "paste" });

		fireEvent.change(screen.getByLabelText("Plot boundary"), {
			target: { value: "not geojson" },
		});

		expect(screen.getByText(/expected "latitude, longitude"/)).toBeDefined();
		expect(validateGeometry).not.toHaveBeenCalled();
	});

	it("shows a server rejection on the geometry field", async () => {
		validateGeometry.mockRejectedValue(
			new ApiClientError({
				operation: "validateGeometry",
				cause: new Error("rejected"),
				status: 422,
				issues: [
					{
						field: "plot.geometry",
						message: "Self-intersection at or near point 101 0.5",
					},
				],
			}),
		);
		renderStep({ plotMethod: "paste" });

		fireEvent.change(screen.getByLabelText("Plot boundary"), {
			target: { value: JSON.stringify(SQUARE) },
		});

		await waitFor(() =>
			expect(
				screen.getAllByText(/Self-intersection at or near point/).length,
			).toBeGreaterThan(0),
		);
		expect(screen.getByText("Rejected")).toBeDefined();
	});

	it("requires a declared area with the 4 ha hint for a point", () => {
		renderStep({
			plotMethod: "point",
			pointLat: "0.73",
			pointLon: "101.87",
		});

		expect(screen.getByLabelText(/Latitude/)).toBeDefined();
		expect(screen.getByLabelText(/Longitude/)).toBeDefined();
		expect(screen.getByLabelText(/Plot area/)).toBeDefined();
		expect(
			screen.getByText("EUDR allows a single point only for plots up to 4 ha."),
		).toBeDefined();
	});

	it("offers the file input without a map", () => {
		renderStep({ plotMethod: "upload" });

		const input = document.querySelector('input[type="file"]');
		expect(input).not.toBeNull();
		expect(input?.getAttribute("accept")).toContain(".geojson");
	});
});

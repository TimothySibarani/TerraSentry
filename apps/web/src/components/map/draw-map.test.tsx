import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DrawMap } from "./draw-map";

const state = vi.hoisted(() => ({
	add: vi.fn(),
	change: {} as Record<string, (...args: unknown[]) => void>,
	snapshot: vi.fn(),
}));
vi.mock("maplibre-gl", () => ({
	setWorkerUrl: vi.fn(),
	NavigationControl: class {},
	ScaleControl: class {},
	Map: class {
		addControl() {}
		fitBounds() {}
		remove() {}
		loaded() {
			return true;
		}
		getLayer() {
			return null;
		}
		on(event: string, fn: () => void) {
			if (event === "load") queueMicrotask(fn);
		}
	},
}));
vi.mock("maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url", () => ({
	default: "worker",
}));
vi.mock("terra-draw-maplibre-gl-adapter", () => ({
	TerraDrawMapLibreGLAdapter: class {},
}));
vi.mock("terra-draw", () => ({
	TerraDrawPolygonMode: class {},
	ValidateNotSelfIntersecting: () => ({ valid: true }),
	TerraDraw: class {
		start() {}
		stop() {}
		setMode() {}
		clear() {}
		removeFeatures() {}
		addFeatures(features: unknown) {
			state.add(features);
		}
		getSnapshot() {
			return state.snapshot();
		}
		on(event: string, fn: (...args: unknown[]) => void) {
			state.change[event] = fn;
		}
	},
}));
afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});
it("loads a complete simple polygon and emits edited geometry", async () => {
	const value = {
		type: "Polygon" as const,
		coordinates: [
			[
				[101, 0],
				[101.01, 0],
				[101.01, 0.01],
				[101, 0],
			],
		],
	};
	state.snapshot.mockReturnValue([]);
	const onChange = vi.fn();
	render(<DrawMap value={value} onChange={onChange} />);
	await waitFor(() => expect(state.add).toHaveBeenCalled());
	expect(state.add.mock.calls[0]?.[0]?.[0]?.geometry).toEqual(value);
	expect(onChange).not.toHaveBeenCalled();
	const edited = {
		...value,
		coordinates: [
			[
				[101, 0],
				[101.02, 0],
				[101.01, 0.01],
				[101, 0],
			],
		],
	};
	state.snapshot.mockReturnValue([{ geometry: edited }]);
	state.change.change?.([], "update");
	expect(onChange).toHaveBeenCalledWith(edited);
});

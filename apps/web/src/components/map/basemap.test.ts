import { describe, expect, it } from "vitest";

import { LOSS_LAYER_ID, satelliteStyle } from "./basemap";

describe("satellite basemap style", () => {
	it("requests display-ready true-color GFW loss tiles", () => {
		const style = satelliteStyle({ showLoss: true });
		const loss = style.sources.loss as { tiles: string[] };
		expect(loss.tiles[0]).toContain("umd_tree_cover_loss");
		expect(loss.tiles[0]).toContain("start_year=2021");
		expect(loss.tiles[0]).toContain("render_type=true_color");
	});

	it("keeps the loss overlay above imagery and below labels", () => {
		const style = satelliteStyle({ showLoss: true });
		const ids = style.layers.map((layer) => layer.id);
		expect(ids).toEqual(["background", "imagery", LOSS_LAYER_ID, "labels"]);
	});

	it("hides the loss layer when showLoss is false", () => {
		const style = satelliteStyle({ showLoss: false });
		const loss = style.layers.find((layer) => layer.id === LOSS_LAYER_ID);
		expect(loss?.layout?.visibility).toBe("none");
	});
});

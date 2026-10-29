import { expect, it } from "vitest";

import { type DatasetCard, splitCards } from "./work-context";

const card = (key: string): DatasetCard => ({
	key,
	title: key,
	source: "",
	metric: "",
	status: "ok",
	agent: "a",
	stepId: key,
});

it("puts the supplier's declarations apart from the datasets they are checked against", () => {
	const { declared, checked } = splitCards([
		card("get_tree_cover_loss"),
		card("get_legality_record"),
		card("layer:peat"),
		card("get_consignment"),
		card("check_concession_overlap"),
	]);
	expect(declared.map((c) => c.key)).toEqual([
		"get_legality_record",
		"get_consignment",
	]);
	expect(checked.map((c) => c.key)).toEqual([
		"get_tree_cover_loss",
		"layer:peat",
		"check_concession_overlap",
	]);
});

/**
 * What each specialist tool is given and what it reads. Agents pass only ids; the tool
 * resolves them against the run input, then queries the external datasets listed here.
 * Mirrors `build_source_tools` (python/core/.../tools/agent_tools.py) and the layer
 * definitions in python/integrations/.../sources/gfw_layers.py.
 */
export interface ToolSpec {
	name: string;
	agent: string;
	/** The part of the run input the id resolves to. */
	reads: string;
	/** External datasets queried; empty when the tool only reads the declared record. */
	datasets: ReadonlyArray<string>;
	deepDive?: boolean;
}

export const SOURCE_TOOLS: ReadonlyArray<ToolSpec> = [
	{
		name: "get_tree_cover_loss",
		agent: "geospatial analyst",
		reads: "Plot geometry",
		datasets: ["Hansen GFC umd_tree_cover_loss", "Context layer summary"],
	},
	{
		name: "get_context_layers",
		agent: "geospatial analyst",
		reads: "Plot geometry",
		datasets: [
			"WDPA protected areas",
			"IDN forest moratorium",
			"GFW oil palm concessions",
			"GFW wood fibre concessions",
			"GFW logging concessions",
			"GFW peatlands",
			"JRC forest baseline 2020",
		],
		deepDive: true,
	},
	{
		name: "get_fire_hotspots",
		agent: "thermal analyst",
		reads: "Plot geometry",
		datasets: ["NASA FIRMS VIIRS"],
	},
	{
		name: "get_legality_record",
		agent: "legality analyst",
		reads: "Supplier & permit",
		datasets: [],
	},
	{
		name: "get_consignment",
		agent: "legality analyst",
		reads: "Consignment",
		datasets: [],
	},
	{
		name: "check_concession_overlap",
		agent: "legality analyst",
		reads: "Plot geometry + declared holder",
		datasets: ["GFW concession layers"],
		deepDive: true,
	},
	{
		name: "search_adverse_media",
		agent: "legality analyst",
		reads: "Supplier name",
		datasets: ["Sonar web search (context only)"],
	},
];

export const toolSpec = (name: string) =>
	SOURCE_TOOLS.find((tool) => tool.name === name);

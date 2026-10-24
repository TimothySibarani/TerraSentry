import type {
	Commodity,
	FieldIssue,
	PermitStatus,
	PermitType,
	RecordSubmission,
} from "@terrasentry/api-client";

import type { PlotGeometry } from "#/features/intake/geometry";

export const STEPS = [
	{
		id: "plot",
		title: "Plot",
		description: "Boundary on the map, pasted, or uploaded",
	},
	{
		id: "supplier",
		title: "Supplier",
		description: "Legal entity operating the plot",
	},
	{
		id: "legality",
		title: "Legality",
		description: "Declared HGU / PBPH permit",
	},
	{
		id: "consignment",
		title: "Consignment",
		description: "Commodity and lot in the DDS",
	},
	{
		id: "review",
		title: "Review & screen",
		description: "Check, pick a model, start the agents",
	},
] as const;

export type StepId = (typeof STEPS)[number]["id"];
export const STEP_IDS: ReadonlyArray<StepId> = STEPS.map((step) => step.id);

export type PlotMethod = "draw" | "paste" | "upload" | "point";

export interface IntakeForm {
	plotMethod: PlotMethod;
	/** Polygon from draw/paste/upload; points are derived from the lat/lon fields. */
	shape: PlotGeometry | null;
	pasteText: string;
	uploadName: string | null;
	pointLat: string;
	pointLon: string;
	declaredAreaHa: string;
	label: string;
	country: string;
	province: string;
	kabupaten: string;
	legalName: string;
	tradingName: string;
	group: string;
	nib: string;
	npwp: string;
	certifications: ReadonlyArray<string>;
	owners: string;
	permitType: PermitType;
	permitNumber: string;
	permitExpiry: string;
	declaredHolder: string;
	permitStatus: PermitStatus;
	concessionAreaHa: string;
	commodity: Commodity;
	description: string;
	hsHeading: string;
	speciesScientific: string;
	speciesCommon: string;
	netWeightKg: string;
	harvestYear: string;
}

export const COMMODITIES: ReadonlyArray<{
	value: Commodity;
	label: string;
	hs: string;
	scientific: string;
	common: string;
	description: string;
}> = [
	{
		value: "oil_palm",
		label: "Oil palm",
		hs: "1511",
		scientific: "Elaeis guineensis",
		common: "Kelapa sawit",
		description: "Crude palm oil",
	},
	{
		value: "rubber",
		label: "Rubber",
		hs: "4001",
		scientific: "Hevea brasiliensis",
		common: "Karet",
		description: "Natural rubber, technically specified",
	},
	{
		value: "cocoa",
		label: "Cocoa",
		hs: "1801",
		scientific: "Theobroma cacao",
		common: "Kakao",
		description: "Cocoa beans, whole, raw",
	},
	{
		value: "coffee",
		label: "Coffee",
		hs: "0901",
		scientific: "",
		common: "Kopi",
		description: "Green coffee, not roasted",
	},
	{
		value: "wood",
		label: "Wood",
		hs: "4403",
		scientific: "",
		common: "",
		description: "Wood in the rough",
	},
];

/** Typical wood lots a fibre buyer screens; they fill the description and HS heading only. */
export const WOOD_LOTS: ReadonlyArray<{
	label: string;
	hs: string;
	description: string;
}> = [
	{
		label: "Wood pulp",
		hs: "4703",
		description: "Chemical wood pulp, bleached hardwood kraft",
	},
	{
		label: "Paper",
		hs: "4802",
		description: "Uncoated paper for writing and printing",
	},
	{
		label: "Logs",
		hs: "4403",
		description: "Wood in the rough",
	},
];

export const CERTIFICATIONS = [
	"ISPO",
	"RSPO",
	"FSC",
	"PEFC",
	"Rainforest Alliance",
] as const;

export const PERMIT_TYPES: ReadonlyArray<{
	value: PermitType;
	label: string;
	description: string;
}> = [
	{
		value: "hgu",
		label: "HGU",
		description:
			"Hak Guna Usaha — plantation land-use right (oil palm, rubber, cocoa).",
	},
	{
		value: "pbph",
		label: "PBPH",
		description:
			"Perizinan Berusaha Pemanfaatan Hutan — forest utilisation licence (wood).",
	},
	{
		value: "none",
		label: "No permit declared",
		description:
			"Smallholder or unknown. The rubric scores this as a data gap.",
	},
];

export function initialForm(): IntakeForm {
	return {
		plotMethod: "draw",
		shape: null,
		pasteText: "",
		uploadName: null,
		pointLat: "",
		pointLon: "",
		declaredAreaHa: "",
		label: "",
		country: "",
		province: "",
		kabupaten: "",
		legalName: "",
		tradingName: "",
		group: "",
		nib: "",
		npwp: "",
		certifications: [],
		owners: "",
		permitType: "hgu",
		permitNumber: "",
		permitExpiry: "",
		declaredHolder: "",
		permitStatus: "active",
		concessionAreaHa: "",
		commodity: "oil_palm",
		description: "Crude palm oil",
		hsHeading: "",
		speciesScientific: "Elaeis guineensis",
		speciesCommon: "Kelapa sawit",
		netWeightKg: "",
		harvestYear: String(new Date().getFullYear()),
	};
}

function toNumber(value: string): number | null {
	const trimmed = value.trim().replace(/,/g, "");
	if (!trimmed) {
		return null;
	}
	const parsed = Number(trimmed);
	return Number.isFinite(parsed) ? parsed : Number.NaN;
}

/** The geometry that would be submitted, or null when the plot is incomplete. */
export function currentGeometry(form: IntakeForm): PlotGeometry | null {
	if (form.plotMethod !== "point") {
		return form.shape;
	}
	const lat = toNumber(form.pointLat);
	const lon = toNumber(form.pointLon);
	if (
		lat === null ||
		lon === null ||
		Number.isNaN(lat) ||
		Number.isNaN(lon) ||
		Math.abs(lat) > 90 ||
		Math.abs(lon) > 180
	) {
		return null;
	}
	return { type: "Point", coordinates: [lon, lat] };
}

export function declaredArea(form: IntakeForm): number | null {
	if (currentGeometry(form)?.type !== "Point") {
		return null;
	}
	const area = toNumber(form.declaredAreaHa);
	return area === null || Number.isNaN(area) ? null : area;
}

export type FieldErrors = Readonly<Record<string, string>>;

/** Client-side checks per step; the server re-validates everything. */
export function validateStep(step: StepId, form: IntakeForm): FieldErrors {
	const errors: Record<string, string> = {};
	if (step === "plot") {
		if (!/^[A-Z]{2}$/.test(form.country.trim().toUpperCase())) {
			errors["plot.country"] =
				"Enter the ISO country code, e.g. ID for Indonesia.";
		}
		const geometry = currentGeometry(form);
		if (!geometry) {
			errors["plot.geometry"] =
				form.plotMethod === "point"
					? "Enter a latitude and longitude in decimal degrees."
					: "Add the plot boundary: draw it, paste coordinates, or upload GeoJSON.";
		}
		if (geometry?.type === "Point") {
			const area = toNumber(form.declaredAreaHa);
			if (area === null || Number.isNaN(area) || area <= 0) {
				errors["plot.declared_area_ha"] = "Enter the plot area in hectares.";
			} else if (area > 4) {
				errors["plot.declared_area_ha"] =
					"Plots over 4 ha must be mapped as a polygon (EUDR Art. 2(28)).";
			}
		}
		if (!form.label.trim()) {
			errors["plot.label"] = "Name the plot, e.g. the estate block.";
		}
	}
	if (step === "supplier" && form.legalName.trim().length < 2) {
		errors["supplier.legal_name"] =
			"Enter the supplier's registered legal name.";
	}
	if (step === "legality") {
		if (
			form.permitExpiry &&
			(!/^\d{4}-\d{2}-\d{2}$/.test(form.permitExpiry) ||
				!Number.isFinite(Date.parse(form.permitExpiry)))
		) {
			errors["legality.permit_expiry"] = "Enter a valid date.";
		}
		if (form.permitType !== "none" && !form.permitNumber.trim()) {
			errors["legality.permit_number"] = "Enter the permit number.";
		}
		const concession = toNumber(form.concessionAreaHa);
		if (concession !== null && (Number.isNaN(concession) || concession <= 0)) {
			errors["legality.concession_area_ha"] =
				"Enter a positive area in hectares.";
		}
	}
	if (step === "consignment") {
		if (form.description.trim().length < 2) {
			errors["consignment.description"] = "Describe the goods as declared.";
		}
		const weight = toNumber(form.netWeightKg);
		if (weight === null || Number.isNaN(weight) || weight <= 0) {
			errors["consignment.net_weight_kg"] =
				"Enter the net weight in kilograms.";
		}
		const year = toNumber(form.harvestYear);
		if (
			year === null ||
			Number.isNaN(year) ||
			!Number.isInteger(year) ||
			year < 2000 ||
			year > 2100
		) {
			errors["consignment.harvest_year"] = "Enter a four-digit harvest year.";
		}
		const hs = form.hsHeading.replace(/\./g, "").trim();
		if (hs && !/^(\d{4}|\d{6}|\d{8}|\d{10})$/.test(hs)) {
			errors["consignment.hs_heading"] = "HS codes have 4, 6, 8, or 10 digits.";
		}
	}
	return errors;
}

export function stepOfField(field: string): StepId {
	const prefix = field.split(".")[0];
	return STEP_IDS.includes(prefix as StepId) ? (prefix as StepId) : "review";
}

export function issuesToErrors(issues: ReadonlyArray<FieldIssue>): FieldErrors {
	return Object.fromEntries(
		issues.map((issue) => [issue.field, issue.message] as const),
	);
}

function lines(value: string): Array<string> {
	return value
		.split(/\r?\n|;/)
		.map((line) => line.trim())
		.filter(Boolean);
}

export function toSubmission(form: IntakeForm): RecordSubmission {
	const geometry = currentGeometry(form);
	if (!geometry) {
		throw new Error("toSubmission called without a geometry");
	}
	const concession = toNumber(form.concessionAreaHa);
	return {
		plot: {
			geometry: geometry as unknown as Record<string, unknown>,
			country: form.country.trim().toUpperCase(),
			label: form.label.trim(),
			province: form.province.trim(),
			kabupaten: form.kabupaten.trim(),
			declared_area_ha: declaredArea(form),
		},
		supplier: {
			legal_name: form.legalName.trim(),
			trading_name: form.tradingName.trim(),
			group: form.group.trim(),
			nib: form.nib.trim(),
			npwp: form.npwp.trim(),
			certifications: [...form.certifications],
			beneficial_owners: lines(form.owners),
		},
		legality: {
			permit_expiry: form.permitExpiry || null,
			declared_holder: form.declaredHolder.trim(),
			permit_type: form.permitType,
			permit_number: form.permitType === "none" ? "" : form.permitNumber.trim(),
			permit_status: form.permitType === "none" ? "none" : form.permitStatus,
			concession_area_ha:
				concession === null || Number.isNaN(concession) ? null : concession,
			sanctions: [],
		},
		consignment: {
			commodity: form.commodity,
			description: form.description.trim(),
			hs_heading: form.hsHeading.replace(/\./g, "").trim(),
			species_scientific: form.speciesScientific.trim(),
			species_common: form.speciesCommon.trim(),
			net_weight_kg: toNumber(form.netWeightKg) ?? 0,
			harvest_year: Number(form.harvestYear),
		},
	};
}

/** A real-world sample: a ~1,280 ha block in Siak, Riau (GFW shows post-2020 loss here). */
export const SAMPLE_PLOT: IntakeForm["shape"] = {
	type: "Polygon",
	coordinates: [
		[
			[101.8612, 0.7431],
			[101.8905, 0.7398],
			[101.8963, 0.7187],
			[101.8741, 0.7072],
			[101.8538, 0.7219],
			[101.8612, 0.7431],
		],
	],
};

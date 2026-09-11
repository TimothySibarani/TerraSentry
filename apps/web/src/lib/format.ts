import { DateTime } from "effect";

const DATE_TIME_FORMAT = new Intl.DateTimeFormat("en-GB", {
	dateStyle: "medium",
	timeStyle: "short",
	timeZone: "UTC",
});

const DATE_FORMAT = new Intl.DateTimeFormat("en-GB", {
	dateStyle: "medium",
	timeZone: "UTC",
});

const NUMBER_FORMAT = new Intl.NumberFormat("en-GB", {
	maximumFractionDigits: 2,
});

export function formatDateTime(value: DateTime.Utc | null | undefined): string {
	if (!value) {
		return "—";
	}
	return `${DATE_TIME_FORMAT.format(DateTime.toDateUtc(value))} UTC`;
}

export function formatDate(value: DateTime.Utc | null | undefined): string {
	if (!value) {
		return "—";
	}
	return DATE_FORMAT.format(DateTime.toDateUtc(value));
}

export function formatDuration(seconds: number | null | undefined): string {
	if (seconds === null || seconds === undefined) {
		return "—";
	}
	if (seconds < 1) {
		return `${Math.round(seconds * 1000)} ms`;
	}
	if (seconds < 60) {
		return `${NUMBER_FORMAT.format(seconds)} s`;
	}
	const minutes = Math.floor(seconds / 60);
	const remainder = Math.round(seconds % 60);
	return `${minutes}m ${remainder}s`;
}

export function formatNumber(value: number | null | undefined): string {
	if (value === null || value === undefined || Number.isNaN(value)) {
		return "—";
	}
	return NUMBER_FORMAT.format(value);
}

export function formatScore(score: number | null | undefined): string {
	return score === null || score === undefined ? "—" : String(score);
}

export function prettyJson(value: unknown): string {
	return JSON.stringify(value, null, 2);
}

export function truncate(value: string, length = 80): string {
	if (value.length <= length) {
		return value;
	}
	return `${value.slice(0, length - 1)}…`;
}

export function formatValue(value: unknown): string {
	if (value === null || value === undefined) {
		return "—";
	}
	if (typeof value === "string") {
		return value;
	}
	if (typeof value === "number" || typeof value === "boolean") {
		return String(value);
	}
	return truncate(JSON.stringify(value), 120);
}

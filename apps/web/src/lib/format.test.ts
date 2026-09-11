import { DateTime } from "effect";
import { describe, expect, it } from "vitest";

import {
	formatDateTime,
	formatDuration,
	formatNumber,
	formatScore,
	formatValue,
	prettyJson,
	truncate,
} from "./format";

describe("format helpers", () => {
	it("formats durations from seconds", () => {
		expect(formatDuration(0.5)).toBe("500 ms");
		expect(formatDuration(2.4)).toBe("2.4 s");
		expect(formatDuration(90)).toBe("1m 30s");
		expect(formatDuration(null)).toBe("—");
	});

	it("formats numbers with at most two decimals", () => {
		expect(formatNumber(1234.567)).toBe("1,234.57");
		expect(formatNumber(null)).toBe("—");
	});

	it("formats scores", () => {
		expect(formatScore(0)).toBe("0");
		expect(formatScore(null)).toBe("—");
	});

	it("renders DateTime values in UTC", () => {
		const value = DateTime.makeUnsafe("2026-09-11T10:30:00Z");
		expect(formatDateTime(value)).toContain("2026");
		expect(formatDateTime(null)).toBe("—");
	});

	it("truncates long strings with an ellipsis", () => {
		expect(truncate("short", 10)).toBe("short");
		expect(truncate("a very long string", 8)).toBe("a very …");
	});

	it("formats unknown evidence values", () => {
		expect(formatValue(null)).toBe("—");
		expect(formatValue("text")).toBe("text");
		expect(formatValue(42)).toBe("42");
		expect(formatValue({ a: 1 })).toBe('{"a":1}');
	});

	it("pretty-prints JSON", () => {
		expect(prettyJson({ a: 1 })).toBe('{\n  "a": 1\n}');
	});
});

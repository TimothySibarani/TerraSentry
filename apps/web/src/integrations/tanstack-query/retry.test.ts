import { ApiClientError } from "@terrasentry/api-client";
import { describe, expect, it } from "vitest";

import { shouldRetryQuery } from "./retry";

const apiError = (status: number | null) =>
	new ApiClientError({
		operation: "test",
		cause: new Error("boom"),
		status,
	});

describe("query retry policy", () => {
	it("does not retry 4xx responses", () => {
		expect(shouldRetryQuery(0, apiError(404))).toBe(false);
		expect(shouldRetryQuery(0, apiError(409))).toBe(false);
		expect(shouldRetryQuery(0, apiError(422))).toBe(false);
	});

	it("retries 5xx responses up to the attempt cap", () => {
		expect(shouldRetryQuery(0, apiError(500))).toBe(true);
		expect(shouldRetryQuery(2, apiError(503))).toBe(true);
		expect(shouldRetryQuery(3, apiError(500))).toBe(false);
	});

	it("retries transport failures up to the attempt cap", () => {
		expect(shouldRetryQuery(0, apiError(null))).toBe(true);
		expect(shouldRetryQuery(3, apiError(null))).toBe(false);
	});

	it("retries unknown errors up to the attempt cap", () => {
		expect(shouldRetryQuery(0, new Error("unexpected"))).toBe(true);
		expect(shouldRetryQuery(3, new Error("unexpected"))).toBe(false);
	});
});

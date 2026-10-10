import { ApiClientError } from "@terrasentry/api-client";
import { describe, expect, it } from "vitest";

import { describeError } from "./error-state";

describe("describeError", () => {
	it("describes an ApiClientError with no status as unreachable", () => {
		const error = new ApiClientError({
			operation: "listRuns",
			cause: new Error("boom"),
			status: null,
		});
		expect(describeError(error).title).toBe("API unreachable");
	});

	it("recognises an ApiClientError serialised across SSR", () => {
		const unreachable = {
			_tag: "ApiClientError",
			operation: "getRun",
			status: null,
		};
		expect(describeError(unreachable).title).toBe("API unreachable");
		expect(describeError({ ...unreachable, status: 404 }).title).toBe(
			"Not found",
		);
	});

	it("recognises a hydrated plain Error carrying the ApiClientError message", () => {
		const error = new ApiClientError({
			operation: "listRuns",
			cause: new Error("boom"),
			status: null,
		});
		expect(describeError(new Error(error.message)).title).toBe("API unreachable");
		expect(describeError(new Error("getRun: HTTP 404")).title).toBe("Not found");
	});

	it("never renders an empty message", () => {
		expect(describeError(new Error("")).message).not.toBe("");
	});
});

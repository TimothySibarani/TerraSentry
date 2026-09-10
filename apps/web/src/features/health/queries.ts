import { queryOptions } from "@tanstack/react-query";
import { Effect } from "effect";

import { runApi } from "../../lib/api";

export function healthQuery() {
	return queryOptions({
		queryKey: ["health"],
		queryFn: () =>
			runApi((api) =>
				api.getHealth().pipe(
					Effect.map((health) => ({
						online: true as const,
						status: health.status,
					})),
					Effect.catch(() =>
						Effect.succeed({ online: false as const, status: "unreachable" }),
					),
				),
			),
	});
}

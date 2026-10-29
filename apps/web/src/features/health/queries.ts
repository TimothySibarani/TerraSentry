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
						offline: health.offline,
						fixturesLoaded: health.fixtures_loaded,
						sapMode: health.sap_mode,
						sapReal: health.sap_real,
						aicoreConfigured: health.aicore_configured,
						adverseMediaMode: health.adverse_media_mode,
						defaultModel: health.default_model,
						gfwConfigured: health.gfw_configured,
						firmsConfigured: health.firms_configured,
						authEnabled: health.auth_enabled,
					})),
					Effect.catch(() =>
						Effect.succeed({
							online: false as const,
							status: "unreachable",
							offline: false,
							fixturesLoaded: 0,
							sapMode: "unknown",
							sapReal: false,
							aicoreConfigured: false,
							adverseMediaMode: "off",
							defaultModel: "scripted",
							gfwConfigured: false,
							firmsConfigured: false,
							authEnabled: false,
						}),
					),
				),
			),
		staleTime: 15_000,
		refetchInterval: 30_000,
	});
}

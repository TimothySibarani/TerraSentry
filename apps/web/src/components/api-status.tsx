import { useQuery } from "@tanstack/react-query";

import { SapModeBadge } from "#/components/sap-panel";
import { Badge } from "#/components/ui/badge";
import { healthQuery } from "#/features/health/queries";

export function ApiStatus() {
	const { data, isPending } = useQuery(healthQuery());
	if (isPending) {
		return <Badge variant="outline">Checking API…</Badge>;
	}
	if (!data?.online) {
		return <Badge variant="risk">API offline</Badge>;
	}
	return (
		<>
			{data.offline || data.fixturesLoaded > 0 ? (
				<Badge variant="review">
					Rehearsal data
					{data.fixturesLoaded > 0 ? ` · ${data.fixturesLoaded} fixtures` : ""}
				</Badge>
			) : (
				<Badge variant="compliant">Live API</Badge>
			)}
			{data.sapMode !== "unknown" && (
				<span className="group-data-[collapsible=icon]:hidden">
					<SapModeBadge mode={data.sapMode} real={data.sapReal} />
				</span>
			)}
		</>
	);
}

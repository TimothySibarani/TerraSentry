import { useQuery } from "@tanstack/react-query";

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
	if (data.offline || data.fixturesLoaded > 0) {
		return (
			<Badge variant="review">
				Rehearsal data
				{data.fixturesLoaded > 0 ? ` · ${data.fixturesLoaded} fixtures` : ""}
			</Badge>
		);
	}
	return <Badge variant="compliant">Live API</Badge>;
}

import type { ReactNode } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "#/components/ui/card";

export function MetricCard({
	label,
	value,
	hint,
}: {
	label: string;
	value: ReactNode;
	hint?: ReactNode;
}) {
	return (
		<Card size="sm">
			<CardHeader>
				<CardTitle className="eyebrow-sm text-muted-foreground">
					{label}
				</CardTitle>
			</CardHeader>
			<CardContent className="flex flex-col gap-1">
				<p className="text-display-xs tabular-nums text-foreground">{value}</p>
				{hint && <p className="text-body-sm text-muted-foreground">{hint}</p>}
			</CardContent>
		</Card>
	);
}

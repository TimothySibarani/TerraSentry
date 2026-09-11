import type { ReactNode } from "react";

import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "#/components/ui/table";

export interface KpiRow {
	metric: string;
	target: string;
	value: ReactNode;
	source: string;
}

/** Static KPI table mirroring `docs/kpi.md`, measured from the latest batch. */
export function KpiTable({ rows }: { rows: KpiRow[] }) {
	return (
		<Table>
			<TableHeader>
				<TableRow>
					<TableHead>Metric</TableHead>
					<TableHead>Target</TableHead>
					<TableHead>Measured</TableHead>
					<TableHead>Source</TableHead>
				</TableRow>
			</TableHeader>
			<TableBody>
				{rows.map((row) => (
					<TableRow key={row.metric}>
						<TableCell className="font-medium text-foreground">
							{row.metric}
						</TableCell>
						<TableCell className="text-muted-foreground">
							{row.target}
						</TableCell>
						<TableCell className="tabular-nums text-foreground">
							{row.value}
						</TableCell>
						<TableCell className="text-caption-mono-sm text-muted-foreground">
							{row.source}
						</TableCell>
					</TableRow>
				))}
			</TableBody>
		</Table>
	);
}

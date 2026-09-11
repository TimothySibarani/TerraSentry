import type { BatchSummary } from "@terrasentry/api-client";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { createColumnHelper } from "@tanstack/react-table";

import { DataTable, type TableFeatureSet } from "#/components/data-table";
import { ErrorState } from "#/components/error-state";
import { PageHeader } from "#/components/page-header";
import { RunStateBadge } from "#/components/status-badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "#/components/ui/card";
import { Skeleton } from "#/components/ui/skeleton";
import { RunLauncher } from "#/features/runs/launcher";
import { batchRunsQuery } from "#/features/runs/queries";
import { formatDateTime, formatDuration, formatNumber } from "#/lib/format";

export const Route = createFileRoute("/batch/")({
	loader: ({ context }) =>
		context.queryClient.ensureQueryData(batchRunsQuery()),
	component: BatchListPage,
});

const helper = createColumnHelper<TableFeatureSet, BatchSummary>();

const columns = helper.columns([
	helper.accessor("run_id", {
		header: "Batch",
		cell: (info) => (
			<span className="font-mono text-xs text-foreground">
				{info.getValue()}
			</span>
		),
	}),
	helper.accessor("state", {
		header: "State",
		cell: (info) => <RunStateBadge state={info.getValue()} />,
	}),
	helper.accessor("record_count", {
		header: "Records",
		cell: (info) => (
			<span className="tabular-nums text-body-sm">
				{formatNumber(info.getValue())}
			</span>
		),
	}),
	helper.accessor("wall_clock_seconds", {
		header: "Wall clock",
		cell: (info) => (
			<span className="tabular-nums text-body-sm">
				{formatDuration(info.getValue())}
			</span>
		),
	}),
	helper.accessor("average_seconds_per_record", {
		header: "Avg / record",
		cell: (info) => (
			<span className="tabular-nums text-body-sm">
				{formatDuration(info.getValue())}
			</span>
		),
	}),
	helper.accessor("started_at", {
		header: "Started",
		cell: (info) => (
			<span className="text-caption-mono-sm text-muted-foreground">
				{formatDateTime(info.getValue())}
			</span>
		),
	}),
]);

function BatchListPage() {
	const navigate = useNavigate();
	const batches = useQuery(batchRunsQuery());

	return (
		<div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
			<PageHeader
				eyebrow="Throughput"
				title="Batch runs"
				description="The 50-record synthetic batch: real GFW/FIRMS calls per record, synthetic legality fields, and the empirical numbers behind the KPI table."
			/>
			<Card>
				<CardHeader>
					<CardTitle>Queue a batch</CardTitle>
					<CardDescription>
						Record IDs are deterministic (REC-001…REC-050) and the expected
						breakdown is 30 compliant / 12 high-risk / 8 ambiguous.
					</CardDescription>
				</CardHeader>
				<CardContent>
					<RunLauncher showScenarios={false} />
				</CardContent>
			</Card>
			{batches.isPending && <Skeleton className="h-64" />}
			{batches.isError && (
				<ErrorState
					error={batches.error}
					onRetry={() => void batches.refetch()}
				/>
			)}
			{!batches.isPending && !batches.isError && (
				<DataTable
					caption="Batch runs"
					columns={columns}
					data={batches.data ?? []}
					emptyMessage="No batch runs yet. Queue one above."
					initialSorting={[{ id: "started_at", desc: true }]}
					getRowId={(batch) => batch.run_id}
					onRowClick={(batch) =>
						void navigate({
							to: "/batch/$batchId",
							params: { batchId: batch.run_id },
						})
					}
				/>
			)}
		</div>
	);
}

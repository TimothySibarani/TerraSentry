import type { RunSummary } from "@terrasentry/api-client";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { createColumnHelper } from "@tanstack/react-table";
import { useMemo } from "react";

import { DataTable, type TableFeatureSet } from "#/components/data-table";
import { ErrorState } from "#/components/error-state";
import { PageHeader } from "#/components/page-header";
import { RunStateBadge, VerdictBadge } from "#/components/status-badge";
import { Skeleton } from "#/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "#/components/ui/tabs";
import { runsQuery } from "#/features/runs/queries";
import { formatDateTime, formatDuration, formatScore } from "#/lib/format";

export const Route = createFileRoute("/runs/")({
	validateSearch: (search: Record<string, unknown>): { kind?: string } => ({
		kind: typeof search.kind === "string" ? search.kind : undefined,
	}),
	loader: ({ context }) => context.queryClient.ensureQueryData(runsQuery()),
	component: RunsPage,
});

const KINDS = [
	{ value: "all", label: "All" },
	{ value: "scenario", label: "Scenarios" },
	{ value: "batch", label: "Batch runs" },
	{ value: "record", label: "Batch records" },
] as const;

const helper = createColumnHelper<TableFeatureSet, RunSummary>();

const columns = helper.columns([
	helper.accessor("record_id", {
		header: "Record",
		cell: (info) => (
			<span className="flex flex-col">
				<span className="font-mono text-xs text-foreground">
					{info.getValue() ?? info.row.original.run_id}
				</span>
				<span className="text-caption-mono-sm text-muted-foreground">
					{info.row.original.kind}
				</span>
			</span>
		),
	}),
	helper.accessor("state", {
		header: "State",
		cell: (info) => <RunStateBadge state={info.getValue()} />,
	}),
	helper.accessor("verdict", {
		header: "Verdict",
		cell: (info) => <VerdictBadge verdict={info.getValue()} />,
	}),
	helper.accessor("score", {
		header: "Score",
		cell: (info) => (
			<span className="tabular-nums text-body-sm">
				{formatScore(info.getValue())}
			</span>
		),
	}),
	helper.accessor("model", {
		header: "Model",
		cell: (info) => (
			<span className="text-caption-mono-sm text-muted-foreground">
				{info.getValue()}
			</span>
		),
	}),
	helper.accessor("elapsed_seconds", {
		header: "Elapsed",
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

function RunsPage() {
	const { kind = "all" } = Route.useSearch();
	const navigate = useNavigate({ from: Route.fullPath });
	const runs = useQuery(runsQuery());

	const filtered = useMemo(() => {
		const rows = runs.data ?? [];
		return kind === "all" ? rows : rows.filter((run) => run.kind === kind);
	}, [runs.data, kind]);

	return (
		<div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
			<PageHeader
				eyebrow="Activity"
				title="Runs"
				description="Every scenario, batch parent, and batch record with its state, verdict, and elapsed time."
			/>
			<Tabs
				value={kind}
				onValueChange={(value) =>
					void navigate({ search: { kind: value as string }, replace: true })
				}
			>
				<TabsList>
					{KINDS.map((option) => (
						<TabsTrigger key={option.value} value={option.value}>
							{option.label}
						</TabsTrigger>
					))}
				</TabsList>
			</Tabs>
			{runs.isPending && <Skeleton className="h-64" />}
			{runs.isError && (
				<ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
			)}
			{!runs.isPending && !runs.isError && (
				<DataTable
					caption="Runs"
					columns={columns}
					data={filtered}
					emptyMessage="No runs match this filter yet."
					initialSorting={[{ id: "started_at", desc: true }]}
					getRowId={(run) => run.run_id}
					onRowClick={(run) =>
						void navigate(
							run.kind === "batch"
								? {
										to: "/batch/$batchId",
										params: { batchId: run.run_id },
									}
								: { to: "/runs/$runId", params: { runId: run.run_id } },
						)
					}
				/>
			)}
		</div>
	);
}

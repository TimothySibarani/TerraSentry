import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { createColumnHelper } from "@tanstack/react-table";
import type { RunSummary } from "@terrasentry/api-client";
import { ArrowLeftIcon } from "lucide-react";
import { useMemo } from "react";

import { DataTable, type TableFeatureSet } from "#/components/data-table";
import { ErrorState } from "#/components/error-state";
import { MetricCard } from "#/components/metric-card";
import { PageHeader } from "#/components/page-header";
import { RunStateBadge, VerdictBadge } from "#/components/status-badge";
import { Button } from "#/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "#/components/ui/card";
import { Progress } from "#/components/ui/progress";
import { Skeleton } from "#/components/ui/skeleton";
import { Spinner } from "#/components/ui/spinner";
import { VerdictBreakdown } from "#/components/verdict-breakdown";
import { batchRecordsQuery, batchRunQuery } from "#/features/runs/queries";
import { useBatchStream } from "#/features/runs/use-batch-stream";
import {
	formatDateTime,
	formatDuration,
	formatNumber,
	formatScore,
} from "#/lib/format";

export const Route = createFileRoute("/batch/$batchId")({
	loader: ({ context, params }) =>
		Promise.all([
			context.queryClient.ensureQueryData(batchRunQuery(params.batchId)),
			context.queryClient.ensureQueryData(batchRecordsQuery(params.batchId)),
		]),
	component: BatchDetailPage,
});

const helper = createColumnHelper<TableFeatureSet, RunSummary>();

const columns = helper.columns([
	helper.accessor("record_id", {
		header: "Record",
		cell: (info) => (
			<Link
				to="/runs/$runId"
				params={{ runId: info.row.original.run_id }}
				className="font-mono text-xs text-foreground underline-offset-4 hover:underline"
				onClick={(event) => event.stopPropagation()}
			>
				{info.getValue() ?? info.row.original.run_id}
			</Link>
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
	helper.accessor("expected_archetype", {
		header: "Expected",
		cell: (info) => (
			<span className="text-body-sm text-muted-foreground">
				{info.getValue() ?? "—"}
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
]);

function BatchDetailPage() {
	const { batchId } = Route.useParams();
	// Remount the screen when the batch changes so stream/progress state resets.
	return <BatchDetailScreen key={batchId} batchId={batchId} />;
}

function BatchDetailScreen({ batchId }: { batchId: string }) {
	const navigate = useNavigate();
	const batch = useQuery(batchRunQuery(batchId));
	const records = useQuery(batchRecordsQuery(batchId));

	const seed = useMemo(
		() => ({
			state: batch.data?.state ?? null,
		}),
		[batch.data],
	);
	const stream = useBatchStream(batchId, seed);

	if (batch.isPending) {
		return (
			<div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
				<Skeleton className="h-28" />
				<Skeleton className="h-40" />
				<Skeleton className="h-96" />
			</div>
		);
	}

	if (batch.isError || !batch.data) {
		return (
			<div className="mx-auto w-full max-w-3xl">
				<ErrorState error={batch.error} onRetry={() => void batch.refetch()} />
			</div>
		);
	}

	const summary = batch.data;
	const state = stream.state.state ?? summary.state;
	const progress = stream.state.progress;
	const total = progress?.total ?? summary.record_count;
	const settled = progress
		? progress.completed + progress.failed + progress.awaitingReview
		: (summary.states.complete ?? 0) +
			(summary.states.failed ?? 0) +
			(summary.states.awaiting_review ?? 0);
	const percent = total > 0 ? Math.round((settled / total) * 100) : 0;
	const breakdown = progress?.verdictBreakdown ?? summary.verdict_breakdown;
	const live = stream.status === "live";
	const wallClock = progress?.elapsedSeconds ?? summary.wall_clock_seconds;
	const average =
		live && progress?.elapsedSeconds != null && settled > 0
			? progress.elapsedSeconds / settled
			: summary.average_seconds_per_record;
	const confusion = summary.confusion ?? {};
	const confusionTotal = Object.values(confusion).reduce(
		(sum, row) =>
			sum + Object.values(row).reduce((rowSum, count) => rowSum + count, 0),
		0,
	);
	const matched = Object.entries(confusion).reduce(
		(sum, [archetype, row]) => sum + (row[archetype] ?? 0),
		0,
	);
	const designMatch = confusionTotal > 0 ? matched / confusionTotal : null;
	const cache = summary.cache_stats;
	const sap = summary.sap_actions ?? {};
	const sapCount = (sap.approved ?? 0) + (sap.blocked ?? 0) + (sap.failed ?? 0);

	return (
		<div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
			<Link
				to="/batch"
				className="flex w-fit items-center gap-1 text-body-sm text-muted-foreground no-underline hover:text-foreground"
			>
				<ArrowLeftIcon aria-hidden="true" className="size-3.5" />
				All batches
			</Link>
			<PageHeader
				eyebrow="Batch run"
				title={summary.run_id}
				description={`${summary.record_count} records · queued ${formatDateTime(summary.started_at ?? summary.finished_at)}`}
				actions={
					<>
						<RunStateBadge state={state} />
						{stream.status === "live" && (
							<Button variant="outline" size="sm" disabled>
								<Spinner
									aria-label="Streaming progress"
									data-icon="inline-start"
								/>
								Streaming
							</Button>
						)}
					</>
				}
			/>

			<Card>
				<CardHeader>
					<CardTitle>Progress</CardTitle>
					<CardDescription>
						{settled} of {total} records settled
						{state === "complete" ? " — batch complete" : "…"}
					</CardDescription>
				</CardHeader>
				<CardContent className="flex flex-col gap-4">
					<Progress
						value={percent}
						aria-label={`${percent}% of records settled`}
					/>
					<div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
						<MetricCard
							label="Wall clock"
							value={formatDuration(wallClock)}
							hint={live ? "Live batch elapsed" : "Total elapsed batch time"}
						/>
						<MetricCard
							label="Avg / record"
							value={formatDuration(average)}
							hint={
								live
									? "Elapsed ÷ settled records"
									: "Mean per-record elapsed time"
							}
						/>
						<MetricCard
							label="Awaiting review"
							value={formatNumber(
								progress?.awaitingReview ?? summary.states.awaiting_review ?? 0,
							)}
							hint="Ambiguous records held for HITL"
						/>
						<MetricCard
							label="Failed"
							value={formatNumber(
								progress?.failed ?? summary.states.failed ?? 0,
							)}
							hint="Records that did not settle"
						/>
					</div>
				</CardContent>
			</Card>

			<Card>
				<CardHeader>
					<CardTitle>Throughput</CardTitle>
					<CardDescription>
						Empirical numbers from this run — the same fields backed by the
						rehearsal report.
					</CardDescription>
				</CardHeader>
				<CardContent className="flex flex-col gap-4">
					<div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
						<MetricCard
							label="Throughput"
							value={formatNumber(summary.throughput_records_per_second)}
							hint="Records per second"
						/>
						<MetricCard
							label="Median / record"
							value={formatDuration(summary.median_seconds_per_record)}
							hint="p50 per-record elapsed"
						/>
						<MetricCard
							label="P95 / record"
							value={formatDuration(summary.p95_seconds_per_record)}
							hint="Nearest-rank p95"
						/>
						<MetricCard
							label="Design match"
							value={
								designMatch === null ? "—" : `${Math.round(designMatch * 100)}%`
							}
							hint="Expected archetype mapped to its verdict"
						/>
					</div>
					<p className="text-caption-mono-sm text-muted-foreground">
						{cache
							? `Cache: ${cache.hits ?? 0} hits · ${cache.misses ?? 0} misses · ${cache.writes ?? 0} writes · ${cache.offline_misses ?? 0} offline misses`
							: "Cache: —"}
					</p>
					{sapCount > 0 && (
						<p className="text-caption-mono-sm text-muted-foreground">
							{sapCount} ERP actions: {sap.approved ?? 0} approved ·{" "}
							{sap.blocked ?? 0} blocked · {sap.failed ?? 0} failed
						</p>
					)}
				</CardContent>
			</Card>

			<Card>
				<CardHeader>
					<CardTitle>Pass / fail / ambiguous breakdown</CardTitle>
					<CardDescription>
						Actual verdicts against the intended 30/12/8 distribution.
					</CardDescription>
				</CardHeader>
				<CardContent>
					<VerdictBreakdown
						verdicts={breakdown}
						expected={summary.expected_breakdown}
						total={total}
					/>
				</CardContent>
			</Card>

			<div className="flex flex-col gap-3">
				<div className="flex items-center justify-between gap-3">
					<h2 className="text-display-xs text-foreground">Records</h2>
					{records.isFetching && (
						<span className="flex items-center gap-1 text-caption-mono-sm text-muted-foreground">
							<Spinner aria-label="Refreshing records" />
							Refreshing…
						</span>
					)}
				</div>
				{records.isPending ? (
					<Skeleton className="h-64" />
				) : records.isError ? (
					<ErrorState
						error={records.error}
						onRetry={() => void records.refetch()}
					/>
				) : (
					<DataTable
						caption="Batch records"
						columns={columns}
						data={records.data ?? []}
						emptyMessage="No records have settled yet."
						getRowId={(record) => record.run_id}
						onRowClick={(record) =>
							void navigate({
								to: "/runs/$runId",
								params: { runId: record.run_id },
							})
						}
					/>
				)}
			</div>
		</div>
	);
}

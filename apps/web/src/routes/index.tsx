import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
	ClockIcon,
	LayersIcon,
	ListChecksIcon,
	RadarIcon,
	WifiIcon,
} from "lucide-react";

import { type KpiRow, KpiTable } from "#/components/kpi-table";
import { MetricCard } from "#/components/metric-card";
import { PageHeader } from "#/components/page-header";
import { RunStateBadge, VerdictBadge } from "#/components/status-badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardFooter,
	CardHeader,
	CardTitle,
} from "#/components/ui/card";
import {
	Empty,
	EmptyContent,
	EmptyDescription,
	EmptyHeader,
	EmptyTitle,
} from "#/components/ui/empty";
import { Button } from "#/components/ui/button";
import { Separator } from "#/components/ui/separator";
import { VerdictBreakdown } from "#/components/verdict-breakdown";
import { healthQuery } from "#/features/health/queries";
import { RunLauncher } from "#/features/runs/launcher";
import { batchRunsQuery, runsQuery } from "#/features/runs/queries";
import { formatDateTime, formatDuration, formatNumber } from "#/lib/format";

export const Route = createFileRoute("/")({
	loader: ({ context }) =>
		Promise.all([
			context.queryClient.ensureQueryData(healthQuery()),
			context.queryClient.ensureQueryData(runsQuery()),
			context.queryClient.ensureQueryData(batchRunsQuery()),
		]),
	component: Dashboard,
});

function Dashboard() {
	const health = useQuery(healthQuery());
	const runs = useQuery(runsQuery());
	const batches = useQuery(batchRunsQuery());

	const recentRuns = (runs.data ?? []).slice(0, 8);
	const latestBatch = (batches.data ?? []).find(
		(batch) => batch.state === "complete",
	);

	const apiTone = health.data?.online
		? health.data.offline || health.data.fixturesLoaded > 0
			? "Rehearsal data"
			: "Live API"
		: "Offline";

	const confusion = latestBatch?.confusion ?? {};
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
	const cache = latestBatch?.cache_stats;
	const failed = latestBatch?.states.failed ?? 0;

	const kpiRows: KpiRow[] = [
		{
			metric: "Batch wall clock (50 records)",
			target: "Demo slot; pre-run if longer",
			value: latestBatch ? formatDuration(latestBatch.wall_clock_seconds) : "—",
			source: latestBatch?.run_id ?? "Run the rehearsal",
		},
		{
			metric: "Average per supplier",
			target: "< 2 min (PRD §5)",
			value: latestBatch
				? formatDuration(latestBatch.average_seconds_per_record)
				: "—",
			source: "Per-record elapsed",
		},
		{
			metric: "Throughput",
			target: "Recorded baseline",
			value: latestBatch
				? `${formatNumber(latestBatch.throughput_records_per_second)} rec/s`
				: "—",
			source: "Batch metrics",
		},
		{
			metric: "Design match (30/12/8)",
			target: "100% exact",
			value: designMatch === null ? "—" : `${Math.round(designMatch * 100)}%`,
			source: "Confusion diagonal",
		},
		{
			metric: "HITL branch under load",
			target: "8 ambiguous held",
			value: latestBatch
				? formatNumber(latestBatch.states.awaiting_review ?? 0)
				: "—",
			source: "Run states",
		},
		{
			metric: "Verifier coverage",
			target: "100% accepted",
			value: latestBatch ? (failed === 0 ? "100%" : `${failed} failed`) : "—",
			source: "Run states",
		},
		{
			metric: "Offline replay",
			target: "0 external calls",
			value: cache
				? `${formatNumber(cache.hits)} hits / ${formatNumber(cache.misses)} misses`
				: "—",
			source: "Cache stats",
		},
		{
			metric: "Cycle acceleration",
			target: "98% vs manual",
			value: "Pending baseline",
			source: "docs/kpi.md",
		},
	];

	return (
		<div className="mx-auto flex w-full max-w-7xl flex-col gap-8">
			<PageHeader
				eyebrow="Overview"
				title="Compliance cockpit"
				description="Screen real supplier plots, follow the agent trace, and read the batch throughput the KPI table is built on."
			/>

			<div className="grid gap-4 lg:grid-cols-5">
				<Card className="lg:col-span-3">
					<CardHeader>
						<CardTitle>Screen a supplier plot</CardTitle>
						<CardDescription>
							Draw or upload a real plot boundary, declare the supplier, permit,
							and lot, and the agents check it against live Hansen tree-cover
							loss and NASA FIRMS data. No seed data needed.
						</CardDescription>
					</CardHeader>
					<CardContent className="flex flex-col gap-4">
						<ol className="grid gap-3 sm:grid-cols-3">
							{[
								["Map", "Draw on satellite imagery or paste coordinates"],
								["Declare", "Supplier, HGU/PBPH permit, commodity lot"],
								["Verify", "Live evidence, rubric, verifier, DDS"],
							].map(([title, detail], position) => (
								<li
									key={title}
									className="flex flex-col gap-1 rounded-md border border-border p-3"
								>
									<span className="eyebrow-sm text-muted-foreground">
										{String(position + 1).padStart(2, "0")} · {title}
									</span>
									<span className="text-body-sm text-foreground">{detail}</span>
								</li>
							))}
						</ol>
					</CardContent>
					<CardFooter>
						<Button render={<Link to="/screen" />}>
							<RadarIcon data-icon="inline-start" aria-hidden="true" />
							Screen a plot
						</Button>
					</CardFooter>
				</Card>
				<Card className="lg:col-span-2">
					<CardHeader>
						<CardTitle>Demo scenarios</CardTitle>
						<CardDescription>
							Seeded plots with synthetic legality records, for the rehearsed
							demo and the 50-record throughput batch.
						</CardDescription>
					</CardHeader>
					<CardContent>
						<RunLauncher />
					</CardContent>
				</Card>
			</div>

			<div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
				<MetricCard
					label="API"
					value={
						<span className="flex items-center gap-2">
							<WifiIcon
								aria-hidden="true"
								className="size-4 text-muted-foreground"
							/>
							{apiTone}
						</span>
					}
					hint={
						health.data?.fixturesLoaded
							? `${health.data.fixturesLoaded} cache fixtures primed`
							: "No fixture priming configured"
					}
				/>
				<MetricCard
					label="Runs recorded"
					value={formatNumber(runs.data?.length ?? 0)}
					hint={
						<span className="flex items-center gap-1">
							<ListChecksIcon aria-hidden="true" className="size-3" />
							Scenarios and batch records
						</span>
					}
				/>
				<MetricCard
					label="Batch wall clock"
					value={
						latestBatch ? formatDuration(latestBatch.wall_clock_seconds) : "—"
					}
					hint={
						latestBatch
							? `${latestBatch.record_count} records`
							: "No completed batch yet"
					}
				/>
				<MetricCard
					label="Avg per record"
					value={
						latestBatch
							? formatDuration(latestBatch.average_seconds_per_record)
							: "—"
					}
					hint={
						<span className="flex items-center gap-1">
							<ClockIcon aria-hidden="true" className="size-3" />
							Empirical, from the last batch
						</span>
					}
				/>
			</div>

			<Card>
				<CardHeader>
					<CardTitle>KPI table</CardTitle>
					<CardDescription>
						Mirrors docs/kpi.md; measured from the latest completed batch —
						never projections.
					</CardDescription>
				</CardHeader>
				<CardContent>
					<KpiTable rows={kpiRows} />
				</CardContent>
			</Card>

			<div className="grid gap-6 lg:grid-cols-5">
				<Card className="lg:col-span-3">
					<CardHeader>
						<CardTitle>Recent runs</CardTitle>
						<CardDescription>
							Newest first. Open a run for the live trace, evidence, map, and
							DDS.
						</CardDescription>
					</CardHeader>
					<CardContent>
						{recentRuns.length === 0 ? (
							<Empty>
								<EmptyHeader>
									<EmptyTitle>No runs yet</EmptyTitle>
									<EmptyDescription>
										Start a scenario or queue the 50-record batch above.
									</EmptyDescription>
								</EmptyHeader>
							</Empty>
						) : (
							<ul className="flex flex-col">
								{recentRuns.map((run, index) => (
									<li key={run.run_id}>
										{index > 0 && <Separator />}
										<Link
											to={
												run.kind === "batch"
													? "/batch/$batchId"
													: "/runs/$runId"
											}
											params={
												run.kind === "batch"
													? { batchId: run.run_id }
													: { runId: run.run_id }
											}
											className="flex flex-wrap items-center gap-3 py-2.5 no-underline transition-colors hover:bg-muted/40"
										>
											<span className="font-mono text-xs text-foreground">
												{run.record_id ?? run.run_id}
											</span>
											<RunStateBadge state={run.state} />
											<VerdictBadge verdict={run.verdict} />
											<span className="text-caption-mono-sm text-muted-foreground">
												{run.kind} · {run.model}
											</span>
											<span className="ml-auto text-caption-mono-sm text-muted-foreground">
												{formatDateTime(run.started_at ?? run.created_at)}
											</span>
										</Link>
									</li>
								))}
							</ul>
						)}
					</CardContent>
				</Card>

				<Card className="lg:col-span-2">
					<CardHeader>
						<CardTitle>Latest batch</CardTitle>
						<CardDescription>
							Pass/fail/ambiguous breakdown against the 30/12/8 design.
						</CardDescription>
					</CardHeader>
					<CardContent className="flex flex-col gap-4">
						{latestBatch ? (
							<>
								<VerdictBreakdown
									verdicts={latestBatch.verdict_breakdown}
									expected={latestBatch.expected_breakdown}
									total={latestBatch.record_count}
								/>
								<Separator />
								<div className="grid grid-cols-2 gap-3">
									<div>
										<p className="eyebrow-sm text-muted-foreground">
											Wall clock
										</p>
										<p className="text-body-sm tabular-nums">
											{formatDuration(latestBatch.wall_clock_seconds)}
										</p>
									</div>
									<div>
										<p className="eyebrow-sm text-muted-foreground">
											Avg / record
										</p>
										<p className="text-body-sm tabular-nums">
											{formatDuration(latestBatch.average_seconds_per_record)}
										</p>
									</div>
								</div>
								<Link
									to="/batch/$batchId"
									params={{ batchId: latestBatch.run_id }}
									className="text-body-sm text-foreground underline-offset-4 hover:underline"
								>
									Open batch summary
								</Link>
							</>
						) : (
							<Empty>
								<EmptyHeader>
									<EmptyTitle>No completed batch</EmptyTitle>
									<EmptyDescription>
										Queue the 50-record batch to populate the KPI numbers.
									</EmptyDescription>
								</EmptyHeader>
								<EmptyContent>
									<span className="flex items-center gap-1 text-caption-mono-sm text-muted-foreground">
										<LayersIcon aria-hidden="true" className="size-3" />
										Run it once before the demo to warm the cache
									</span>
								</EmptyContent>
							</Empty>
						)}
					</CardContent>
				</Card>
			</div>
		</div>
	);
}

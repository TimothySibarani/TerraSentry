import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { ClockIcon, LayersIcon, ListChecksIcon, WifiIcon } from "lucide-react";

import { MetricCard } from "#/components/metric-card";
import { PageHeader } from "#/components/page-header";
import { RunStateBadge, VerdictBadge } from "#/components/status-badge";
import {
	Card,
	CardContent,
	CardDescription,
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

	return (
		<div className="mx-auto flex w-full max-w-7xl flex-col gap-8">
			<PageHeader
				eyebrow="Overview"
				title="Compliance cockpit"
				description="Run the two live scenarios, follow the agent trace, and read the batch throughput the KPI table is built on."
			/>

			<Card>
				<CardHeader>
					<CardTitle>Start a due-diligence run</CardTitle>
					<CardDescription>
						Scripted runs replay offline; Bedrock runs use the configured model
						ids. Cached sources keep rehearsals free of external calls.
					</CardDescription>
				</CardHeader>
				<CardContent>
					<RunLauncher />
				</CardContent>
			</Card>

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

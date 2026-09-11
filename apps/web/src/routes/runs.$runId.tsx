import type { TraceStep } from "@terrasentry/api-client";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { ArrowLeftIcon, RefreshCwIcon } from "lucide-react";
import { useMemo } from "react";

import { ErrorState } from "#/components/error-state";
import { PageHeader } from "#/components/page-header";
import { RunStateBadge, VerdictBadge } from "#/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "#/components/ui/alert";
import { Button } from "#/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "#/components/ui/card";
import { Skeleton } from "#/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "#/components/ui/tabs";
import { AssessmentPanel } from "#/features/runs/assessment-panel";
import { DdsDownloadButton, DdsPanel } from "#/features/runs/dds-panel";
import { EvidenceTable } from "#/features/runs/evidence-table";
import {
	runDdsQuery,
	runEvidenceQuery,
	runQuery,
} from "#/features/runs/queries";
import { ReviewDialog } from "#/features/runs/review-dialog";
import { RunMapPanel } from "#/features/runs/run-map";
import { TracePanel } from "#/features/runs/trace-panel";
import { useRunStream } from "#/features/runs/use-run-stream";
import { formatDateTime, formatDuration, formatScore } from "#/lib/format";

export const Route = createFileRoute("/runs/$runId")({
	validateSearch: (search: Record<string, unknown>): { tab?: string } => ({
		tab: typeof search.tab === "string" ? search.tab : undefined,
	}),
	loader: async ({ context, params }) => {
		const run = await context.queryClient.ensureQueryData(
			runQuery(params.runId),
		);
		await context.queryClient.ensureQueryData(runEvidenceQuery(params.runId));
		if (run.dds?.released) {
			await context.queryClient.ensureQueryData(runDdsQuery(params.runId));
		}
	},
	component: RunDetailPage,
});

function RunDetailPage() {
	const { runId } = Route.useParams();
	// Remount the screen when the run changes so stream/trace state resets.
	return <RunDetailScreen key={runId} runId={runId} />;
}

function RunDetailScreen({ runId }: { runId: string }) {
	const { tab = "trace" } = Route.useSearch();
	const navigate = useNavigate({ from: Route.fullPath });
	const run = useQuery(runQuery(runId));
	const evidence = useQuery(runEvidenceQuery(runId));

	const seed = useMemo(
		() => ({
			steps: [...(run.data?.steps ?? [])],
			state: run.data?.state ?? null,
			verdict: run.data?.verdict ?? null,
			score: run.data?.score ?? null,
			ddsReleased: run.data?.dds?.released ?? false,
		}),
		[run.data],
	);
	const stream = useRunStream(runId, seed);

	if (run.isPending) {
		return (
			<div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
				<Skeleton className="h-28" />
				<Skeleton className="h-96" />
			</div>
		);
	}

	if (run.isError || !run.data) {
		return (
			<div className="mx-auto w-full max-w-3xl">
				<ErrorState error={run.error} onRetry={() => void run.refetch()} />
			</div>
		);
	}

	const record = run.data;
	const state = stream.state.state ?? record.state;
	const verdict = stream.state.verdict ?? record.verdict;
	const score = stream.state.score ?? record.score;
	const ddsReleased =
		stream.state.ddsReleased || (record.dds?.released ?? false);
	const steps = mergeSteps(record.steps, stream.state.steps);
	const pendingVerdict = record.pending_assessment;
	const releasedVerdict = record.assessment;

	const tone =
		verdict === "high_risk"
			? "risk"
			: verdict === "ambiguous"
				? "review"
				: verdict === "compliant"
					? "compliant"
					: "neutral";

	return (
		<div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
			<Link
				to="/runs"
				className="flex w-fit items-center gap-1 text-body-sm text-muted-foreground no-underline hover:text-foreground"
			>
				<ArrowLeftIcon aria-hidden="true" className="size-3.5" />
				All runs
			</Link>
			<PageHeader
				eyebrow={`${record.kind} run`}
				title={record.record_id ?? record.run_id}
				description={
					<span className="font-mono text-xs">
						{record.run_id}
						{record.supplier_id ? ` · ${record.supplier_id}` : ""}
						{record.polygon_id ? ` · ${record.polygon_id}` : ""}
					</span>
				}
				actions={
					<>
						<RunStateBadge state={state} />
						<VerdictBadge verdict={verdict} />
						<Button
							variant="outline"
							size="sm"
							onClick={() => void run.refetch()}
						>
							<RefreshCwIcon data-icon="inline-start" aria-hidden="true" />
							Refresh
						</Button>
						{ddsReleased && <DdsDownloadButton runId={record.run_id} />}
						{state === "awaiting_review" && (
							<ReviewDialog runId={record.run_id} />
						)}
					</>
				}
			/>

			{record.kind === "batch" ? (
				<Alert>
					<AlertTitle>This is a batch parent run</AlertTitle>
					<AlertDescription>
						Batch summaries show throughput and the record table.{" "}
						<Link
							to="/batch/$batchId"
							params={{ batchId: record.run_id }}
							className="underline underline-offset-4"
						>
							Open the batch summary
						</Link>
						.
					</AlertDescription>
				</Alert>
			) : null}

			{state === "failed" && record.error && (
				<Alert variant="destructive">
					<AlertTitle>Run failed</AlertTitle>
					<AlertDescription>{record.error}</AlertDescription>
				</Alert>
			)}
			{state === "needs_more_data" && (
				<Alert>
					<AlertTitle>Needs more data</AlertTitle>
					<AlertDescription>
						A source did not answer for this polygon. Re-run with refreshed
						sources once the API keys are available.
					</AlertDescription>
				</Alert>
			)}

			<div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
				<Meta label="Score" value={formatScore(score)} />
				<Meta label="Model" value={record.model} />
				<Meta label="Elapsed" value={formatDuration(record.elapsed_seconds)} />
				<Meta
					label="Started"
					value={formatDateTime(record.started_at ?? record.created_at)}
				/>
			</div>

			<Tabs
				value={tab}
				onValueChange={(value) =>
					void navigate({ search: { tab: value as string }, replace: true })
				}
			>
				<TabsList variant="line">
					<TabsTrigger value="trace">Trace</TabsTrigger>
					<TabsTrigger value="assessment">Assessment</TabsTrigger>
					<TabsTrigger value="evidence">
						Evidence ({evidence.data?.length ?? 0})
					</TabsTrigger>
					<TabsTrigger value="map">Map</TabsTrigger>
					<TabsTrigger value="dds">DDS</TabsTrigger>
				</TabsList>
				<TabsContent value="trace" className="pt-4">
					<Card>
						<CardHeader>
							<CardTitle>Agent trace</CardTitle>
						</CardHeader>
						<CardContent>
							<TracePanel
								steps={steps}
								status={stream.status}
								error={stream.error}
								onReconnect={stream.reconnect}
							/>
						</CardContent>
					</Card>
				</TabsContent>
				<TabsContent value="assessment" className="pt-4">
					<AssessmentPanel
						verdict={releasedVerdict ?? pendingVerdict}
						verification={record.verification}
						disclosures={record.disclosures}
					/>
				</TabsContent>
				<TabsContent value="evidence" className="pt-4">
					{evidence.isPending ? (
						<Skeleton className="h-64" />
					) : evidence.isError ? (
						<ErrorState
							error={evidence.error}
							onRetry={() => void evidence.refetch()}
						/>
					) : (
						<EvidenceTable entries={evidence.data ?? []} />
					)}
				</TabsContent>
				<TabsContent value="map" className="pt-4">
					<RunMapPanel
						entries={evidence.data ?? []}
						tone={tone}
						label={record.polygon_id ?? record.run_id}
					/>
				</TabsContent>
				<TabsContent value="dds" className="pt-4">
					<DdsPanel runId={record.run_id} released={ddsReleased} />
				</TabsContent>
			</Tabs>
		</div>
	);
}

function mergeSteps(
	persisted: ReadonlyArray<TraceStep>,
	live: ReadonlyArray<TraceStep>,
): TraceStep[] {
	const merged = new Map<string, TraceStep>();
	for (const step of persisted) {
		merged.set(step.step_id, step);
	}
	for (const step of live) {
		merged.set(step.step_id, step);
	}
	return [...merged.values()];
}

function Meta({ label, value }: { label: string; value: string }) {
	return (
		<Card size="sm">
			<CardContent className="flex flex-col gap-1">
				<p className="eyebrow-sm text-muted-foreground">{label}</p>
				<p className="truncate text-body-sm tabular-nums text-foreground">
					{value}
				</p>
			</CardContent>
		</Card>
	);
}

import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import type { ModelMode, TraceStep } from "@terrasentry/api-client";
import { adverseMediaFromSteps } from "@terrasentry/api-client";
import { ArrowLeftIcon, RefreshCwIcon, RotateCcwIcon } from "lucide-react";
import { useMemo } from "react";

import { ErrorState } from "#/components/error-state";
import { PageHeader } from "#/components/page-header";
import { SapActionCard } from "#/components/sap-panel";
import {
	ExpectedBadge,
	RunStateBadge,
	VerdictBadge,
} from "#/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "#/components/ui/alert";
import { Button } from "#/components/ui/button";
import { Skeleton } from "#/components/ui/skeleton";
import { Spinner } from "#/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "#/components/ui/tabs";
import { AdverseMediaCard } from "#/features/runs/adverse-media-card";
import { AgentBrief } from "#/features/runs/agent-brief";
import { deriveAgentRun } from "#/features/runs/agent-run";
import { AgentWorkspace } from "#/features/runs/agent-workspace";
import { AssessmentPanel } from "#/features/runs/assessment-panel";
import { DdsDownloadButton, DdsPanel } from "#/features/runs/dds-panel";
import { ErpPendingCard } from "#/features/runs/erp-pending-card";
import { EvidenceTable } from "#/features/runs/evidence-table";
import { useCancelRun, useCreateRun } from "#/features/runs/mutations";
import {
	runDdsQuery,
	runEvidenceQuery,
	runInputQuery,
	runQuery,
} from "#/features/runs/queries";
import { ReviewDialog } from "#/features/runs/review-dialog";
import { RunInputBlock } from "#/features/runs/run-input";
import { RunMapPanel } from "#/features/runs/run-map";
import { RunOverview, useRunClock } from "#/features/runs/run-overview";
import { useRunStream } from "#/features/runs/use-run-stream";

export const Route = createFileRoute("/runs/$runId")({
	validateSearch: (
		search: Record<string, unknown>,
	): { tab?: string; agent?: string; step?: string } => ({
		agent: typeof search.agent === "string" ? search.agent : undefined,
		step: typeof search.step === "string" ? search.step : undefined,
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

// The tabs sit below the overview and input blocks; a link that only switches
// the tab would change nothing the user can see, so bring the tabs into view.
const scrollToTabs = () =>
	requestAnimationFrame(() =>
		document
			.getElementById("run-tabs")
			?.scrollIntoView({ behavior: "smooth", block: "start" }),
	);

function RunDetailScreen({ runId }: { runId: string }) {
	const { tab = "trace", agent, step } = Route.useSearch();
	const navigate = useNavigate({ from: Route.fullPath });
	const run = useQuery(runQuery(runId));
	const evidence = useQuery(runEvidenceQuery(runId));
	// Failed runs have no verdict row, so the design target comes from the stored input.
	const input = useQuery(
		runInputQuery(
			runId,
			run.data?.kind !== "batch" && Boolean(run.data?.record_id),
		),
	);
	const cancel = useCancelRun(runId);
	const rerun = useCreateRun();

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
	const now = useRunClock(stream.state.state ?? run.data?.state ?? "queued");

	if (run.isPending) {
		return (
			<div className="mx-auto flex w-full max-w-[100rem] flex-col gap-6">
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
	const adverseMedia = adverseMediaFromSteps(steps);
	const agentRun = deriveAgentRun(steps, {
		model: record.model,
		state,
		now,
		verification: record.verification,
	});
	const hasBrief =
		record.kind !== "batch" &&
		record.model !== "deterministic" &&
		record.summary.trim() !== "";
	const pendingVerdict = record.pending_assessment;
	const releasedVerdict = record.assessment;
	const inFlight = state === "queued" || state === "running";
	const canRunAgain =
		record.kind !== "batch" && record.record_id !== null && state === "failed";
	const rerunModel: ModelMode | undefined =
		record.model === "scripted" || record.model === "sap"
			? record.model
			: undefined;

	const tone =
		verdict === "high_risk"
			? "risk"
			: verdict === "ambiguous"
				? "review"
				: verdict === "compliant"
					? "compliant"
					: "neutral";

	return (
		<div className="mx-auto flex w-full max-w-[100rem] flex-col gap-6">
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
						<ExpectedBadge
							expected={
								record.expected_archetype ??
								input.data?.record.expected_archetype
							}
							verdict={verdict}
						/>
						<Button
							variant="outline"
							size="sm"
							onClick={() => void run.refetch()}
						>
							<RefreshCwIcon data-icon="inline-start" aria-hidden="true" />
							Refresh
						</Button>
						{ddsReleased && <DdsDownloadButton runId={record.run_id} />}
						{inFlight && (
							<Button
								variant="outline"
								size="sm"
								disabled={cancel.isPending}
								onClick={() => cancel.mutate()}
							>
								{cancel.isPending && (
									<Spinner aria-label="Cancelling" data-icon="inline-start" />
								)}
								Cancel run
							</Button>
						)}
						{canRunAgain && (
							<Button
								variant="outline"
								size="sm"
								disabled={rerun.isPending}
								onClick={() =>
									rerun.mutate(
										{
											record_id: record.record_id ?? undefined,
											model: rerunModel,
											erp_mode: record.erp_mode,
										},
										{
											onSuccess: (created) =>
												void navigate({
													to: "/runs/$runId",
													params: { runId: created.run_id },
												}),
										},
									)
								}
							>
								<RotateCcwIcon data-icon="inline-start" aria-hidden="true" />
								Run again
							</Button>
						)}
						{state === "awaiting_review" && (
							<ReviewDialog
								runId={record.run_id}
								verdict={verdict}
								erpMode={record.erp_mode}
								brief={
									record.model === "deterministic" ? undefined : record.summary
								}
								findings={pendingVerdict?.assessment.findings ?? []}
							/>
						)}
					</>
				}
			/>

			{record.operator_profile && (
				<p className="text-body-sm text-muted-foreground">
					Accepted operator: {record.operator_profile.legal_name} ·{" "}
					{record.operator_profile.identifier_value}
					{record.assessment_date ? ` · as of ${record.assessment_date}` : ""}
				</p>
			)}

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
					<AlertDescription>
						<p>{record.error}</p>
						{record.verification &&
						!record.verification.accepted &&
						record.verification.challenges.length > 0 ? (
							<span className="flex flex-wrap gap-4">
								<Link
									to="/runs/$runId"
									params={{ runId }}
									search={{ tab: "trace", agent: "verifier" }}
									hash="run-tabs"
									onClick={scrollToTabs}
									className="underline underline-offset-4"
								>
									Inspect the verifier
								</Link>
								<Link
									to="/runs/$runId"
									params={{ runId }}
									search={{ tab: "assessment" }}
									hash="run-tabs"
									onClick={scrollToTabs}
									className="underline underline-offset-4"
								>
									View verification
								</Link>
							</span>
						) : null}
					</AlertDescription>
				</Alert>
			)}
			{state === "awaiting_review" && (
				<Alert>
					<AlertTitle>Waiting for your decision</AlertTitle>
					<AlertDescription>
						The rubric verdict is held for a person
						{verdict === "high_risk" ? " because it is high risk" : ""}. The
						statement stays withheld and nothing changes in SAP until someone
						approves or blocks this supplier.
					</AlertDescription>
				</Alert>
			)}
			{(cancel.error || rerun.error) && (
				<ErrorState error={cancel.error ?? rerun.error} />
			)}

			<RunOverview
				run={agentRun}
				score={score}
				started={record.started_at ?? record.created_at}
			/>

			{record.kind !== "batch" && record.erp_pending ? (
				<ErpPendingCard runId={record.run_id} pending={record.erp_pending} />
			) : null}
			{record.kind !== "batch" ? (
				<SapActionCard action={record.sap_action} />
			) : null}

			<RunInputBlock
				runId={record.run_id}
				enabled={record.kind !== "batch" && record.record_id !== null}
				tone={tone}
			/>

			<Tabs
				id="run-tabs"
				className="scroll-mt-4"
				value={tab}
				onValueChange={(value) =>
					void navigate({
						search: (previous) => ({ ...previous, tab: value as string }),
						replace: true,
					})
				}
			>
				<TabsList variant="line">
					<TabsTrigger value="trace">Trace</TabsTrigger>
					{hasBrief && <TabsTrigger value="brief">Brief</TabsTrigger>}
					<TabsTrigger value="assessment">Assessment</TabsTrigger>
					<TabsTrigger value="evidence">
						Evidence ({evidence.data?.length ?? 0})
					</TabsTrigger>
					<TabsTrigger value="map">Map</TabsTrigger>
					<TabsTrigger value="dds">DDS</TabsTrigger>
				</TabsList>
				<TabsContent value="trace" className="pt-4">
					<AgentWorkspace
						run={agentRun}
						model={record.model}
						state={state}
						record={record}
						selectedAgent={agent}
						selectedStep={step}
						onSelect={(agent, step) =>
							void navigate({
								search: (previous) => ({ ...previous, agent, step }),
								replace: true,
							})
						}
						onOpenMap={() =>
							void navigate({
								search: (previous) => ({ ...previous, tab: "map" }),
								replace: true,
							})
						}
						steps={steps}
						status={stream.status}
						error={stream.error}
						onReconnect={stream.reconnect}
					/>
				</TabsContent>
				{hasBrief && (
					<TabsContent value="brief" className="pt-4">
						<AgentBrief
							summary={record.summary}
							model={record.model}
							steps={steps}
						/>
					</TabsContent>
				)}
				<TabsContent value="assessment" className="flex flex-col gap-4 pt-4">
					<AssessmentPanel
						runId={runId}
						verdict={releasedVerdict ?? pendingVerdict}
						verification={record.verification}
						disclosures={record.disclosures}
					/>
					{adverseMedia && <AdverseMediaCard report={adverseMedia} />}
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

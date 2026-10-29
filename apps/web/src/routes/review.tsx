import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { createColumnHelper } from "@tanstack/react-table";
import type { RunSummary } from "@terrasentry/api-client";
import { InboxIcon } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { DataTable, type TableFeatureSet } from "#/components/data-table";
import { ErrorState } from "#/components/error-state";
import { PageHeader } from "#/components/page-header";
import { VerdictBadge } from "#/components/status-badge";
import {
	AlertDialog,
	AlertDialogCancel,
	AlertDialogContent,
	AlertDialogDescription,
	AlertDialogFooter,
	AlertDialogHeader,
	AlertDialogTitle,
} from "#/components/ui/alert-dialog";
import { Button } from "#/components/ui/button";
import { Checkbox } from "#/components/ui/checkbox";
import {
	Empty,
	EmptyDescription,
	EmptyHeader,
	EmptyMedia,
	EmptyTitle,
} from "#/components/ui/empty";
import {
	Field,
	FieldDescription,
	FieldGroup,
	FieldLabel,
} from "#/components/ui/field";
import { Input } from "#/components/ui/input";
import { Skeleton } from "#/components/ui/skeleton";
import { Spinner } from "#/components/ui/spinner";
import { Tabs, TabsList, TabsTrigger } from "#/components/ui/tabs";
import { Textarea } from "#/components/ui/textarea";
import {
	CHOICE_LABEL,
	noteRequired,
	type ReviewChoice,
	sapEffect,
} from "#/features/runs/decision";
import { useBulkDecision } from "#/features/runs/mutations";
import { reviewQueueQuery } from "#/features/runs/queries";
import { formatDateTime, formatScore } from "#/lib/format";

export const Route = createFileRoute("/review")({
	validateSearch: (search: Record<string, unknown>): { verdict?: string } => ({
		verdict: typeof search.verdict === "string" ? search.verdict : undefined,
	}),
	loader: ({ context }) =>
		context.queryClient.ensureQueryData(reviewQueueQuery()),
	head: () => ({ meta: [{ title: "Needs review — TerraSentry" }] }),
	component: ReviewQueuePage,
});

const VERDICT_FILTERS = [
	{ value: "all", label: "All" },
	{ value: "high_risk", label: "High risk" },
	{ value: "ambiguous", label: "Ambiguous" },
] as const;

const helper = createColumnHelper<TableFeatureSet, RunSummary>();

function ReviewQueuePage() {
	const { verdict = "all" } = Route.useSearch();
	const navigate = useNavigate({ from: Route.fullPath });
	const queue = useQuery(reviewQueueQuery());
	const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
	const [pending, setPending] = useState<ReviewChoice | null>(null);

	// Batch parents never wait for review; only their child records and scenarios do.
	const rows = useMemo(
		() =>
			(queue.data ?? []).filter(
				(run) =>
					run.kind !== "batch" &&
					(verdict === "all" || run.verdict === verdict),
			),
		[queue.data, verdict],
	);
	const visibleSelected = rows.filter((run) => selected.has(run.run_id));
	const allSelected = rows.length > 0 && visibleSelected.length === rows.length;

	const toggle = useCallback(
		(runId: string, on: boolean) =>
			setSelected((current) => {
				const next = new Set(current);
				if (on) {
					next.add(runId);
				} else {
					next.delete(runId);
				}
				return next;
			}),
		[],
	);

	const columns = useMemo(
		() =>
			helper.columns([
				helper.display({
					id: "select",
					header: () => (
						<Checkbox
							aria-label="Select all runs in view"
							checked={allSelected}
							indeterminate={visibleSelected.length > 0 && !allSelected}
							onCheckedChange={(checked) =>
								setSelected(
									checked ? new Set(rows.map((run) => run.run_id)) : new Set(),
								)
							}
						/>
					),
					cell: ({ row }) => (
						// The table row navigates on click; selecting must not.
						// biome-ignore lint/a11y/noStaticElementInteractions: stops row navigation only
						<span
							className="inline-flex"
							onClick={(event) => event.stopPropagation()}
							onKeyDown={(event) => event.stopPropagation()}
						>
							<Checkbox
								aria-label={`Select ${row.original.record_id ?? row.original.run_id}`}
								checked={selected.has(row.original.run_id)}
								onCheckedChange={(checked) =>
									toggle(row.original.run_id, checked)
								}
							/>
						</span>
					),
				}),
				helper.accessor("record_id", {
					header: "Record",
					cell: (info) => (
						<span className="flex flex-col">
							<span className="font-mono text-xs text-foreground">
								{info.getValue() ?? info.row.original.run_id}
							</span>
							<span className="text-caption-mono-sm text-muted-foreground">
								{info.row.original.supplier_id ?? "—"}
							</span>
						</span>
					),
				}),
				helper.accessor("verdict", {
					header: "Rubric verdict",
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
					header: "Run",
					cell: (info) => (
						<span className="text-caption-mono-sm text-muted-foreground">
							{info.getValue() === "deterministic"
								? "screening"
								: info.getValue()}
						</span>
					),
				}),
				helper.accessor("finished_at", {
					header: "Held since",
					cell: (info) => (
						<span className="text-caption-mono-sm text-muted-foreground">
							{formatDateTime(info.getValue())}
						</span>
					),
				}),
			]),
		[rows, selected, allSelected, visibleSelected.length, toggle],
	);

	return (
		<div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
			<PageHeader
				eyebrow="Review"
				title="Needs your decision"
				description="Ambiguous and high-risk verdicts wait here. The rubric decided the verdict; you decide the supplier. Nothing changes in SAP until you do."
				actions={
					visibleSelected.length > 0 ? (
						<>
							<span className="text-body-sm text-muted-foreground">
								{visibleSelected.length} selected
							</span>
							<Button size="sm" onClick={() => setPending("override")}>
								Block selected
							</Button>
							<Button
								size="sm"
								variant="outline"
								onClick={() => setPending("approve")}
							>
								Approve selected
							</Button>
						</>
					) : undefined
				}
			/>
			<Tabs
				value={verdict}
				onValueChange={(value) =>
					void navigate({ search: { verdict: value as string }, replace: true })
				}
			>
				<TabsList>
					{VERDICT_FILTERS.map((option) => (
						<TabsTrigger key={option.value} value={option.value}>
							{option.label}
						</TabsTrigger>
					))}
				</TabsList>
			</Tabs>
			{queue.isPending && <Skeleton className="h-64" />}
			{queue.isError && (
				<ErrorState error={queue.error} onRetry={() => void queue.refetch()} />
			)}
			{!queue.isPending &&
				!queue.isError &&
				(rows.length === 0 ? (
					<Empty>
						<EmptyHeader>
							<EmptyMedia variant="icon">
								<InboxIcon aria-hidden="true" />
							</EmptyMedia>
							<EmptyTitle>Nothing is waiting for you</EmptyTitle>
							<EmptyDescription>
								Screen a plot or run a batch. Ambiguous and high-risk results
								appear here for a decision.{" "}
								<Link to="/screen" className="underline underline-offset-4">
									Screen a plot
								</Link>
							</EmptyDescription>
						</EmptyHeader>
					</Empty>
				) : (
					<DataTable
						caption="Runs waiting for a decision"
						columns={columns}
						data={rows}
						initialSorting={[{ id: "finished_at", desc: true }]}
						getRowId={(run) => run.run_id}
						onRowClick={(run) =>
							void navigate({
								to: "/runs/$runId",
								params: { runId: run.run_id },
							})
						}
					/>
				))}
			<BulkDecisionDialog
				choice={pending}
				runs={visibleSelected}
				onClose={() => setPending(null)}
				onDecided={(runIds) =>
					setSelected((current) => {
						const next = new Set(current);
						for (const runId of runIds) {
							next.delete(runId);
						}
						return next;
					})
				}
			/>
		</div>
	);
}

function BulkDecisionDialog({
	choice,
	runs,
	onClose,
	onDecided,
}: {
	choice: ReviewChoice | null;
	runs: ReadonlyArray<RunSummary>;
	onClose: () => void;
	onDecided: (runIds: ReadonlyArray<string>) => void;
}) {
	const [reviewer, setReviewer] = useState("demo-reviewer");
	const [note, setNote] = useState("");
	const bulk = useBulkDecision();

	if (choice === null) {
		return null;
	}
	const needsNote = noteRequired(
		runs.map((run) => run.verdict),
		choice,
	);
	const noteMissing = needsNote && note.trim() === "";
	const modes = new Set(runs.map((run) => run.erp_mode));
	const effect =
		modes.size === 1
			? sapEffect(choice, [...modes][0])
			: "SAP: depends on how each run was started (auto, confirm or off)";
	const result = bulk.data;

	const run = async () => {
		if (noteMissing) {
			return;
		}
		const outcome = await bulk.mutateAsync({
			runIds: runs.map((item) => item.run_id),
			decision: choice,
			reviewer: reviewer.trim() || "human",
			note: note.trim(),
		});
		onDecided(outcome.succeeded);
		if (outcome.failed.length === 0) {
			setNote("");
			bulk.reset();
			onClose();
		}
	};

	return (
		<AlertDialog
			open
			onOpenChange={(open) => {
				if (!open) {
					bulk.reset();
					onClose();
				}
			}}
		>
			<AlertDialogContent>
				<AlertDialogHeader>
					<AlertDialogTitle>
						{CHOICE_LABEL[choice]}: {runs.length} run
						{runs.length === 1 ? "" : "s"}
					</AlertDialogTitle>
					<AlertDialogDescription>
						{effect}. Each run keeps its rubric verdict and gets your decision
						recorded with the note below.
					</AlertDialogDescription>
				</AlertDialogHeader>
				<FieldGroup>
					<Field>
						<FieldLabel htmlFor="bulk-reviewer">Reviewer</FieldLabel>
						<Input
							id="bulk-reviewer"
							autoComplete="off"
							value={reviewer}
							onChange={(event) => setReviewer(event.target.value)}
						/>
					</Field>
					<Field data-invalid={noteMissing || undefined}>
						<FieldLabel htmlFor="bulk-note">
							Note{needsNote ? " (required)" : ""}
						</FieldLabel>
						<Textarea
							id="bulk-note"
							rows={3}
							aria-invalid={noteMissing || undefined}
							value={note}
							onChange={(event) => setNote(event.target.value)}
						/>
						{needsNote && (
							<FieldDescription>
								At least one selected run is high risk. Approving it overrides
								the rubric, so say why.
							</FieldDescription>
						)}
					</Field>
				</FieldGroup>
				{result && result.failed.length > 0 && (
					<div role="alert" className="text-body-sm text-status-risk">
						<p>
							{result.succeeded.length} recorded, {result.failed.length} failed:
						</p>
						<ul className="list-disc pl-5">
							{result.failed.map((failure) => (
								<li key={failure.runId}>
									<span className="font-mono text-xs">{failure.runId}</span>:{" "}
									{failure.message}
								</li>
							))}
						</ul>
					</div>
				)}
				<AlertDialogFooter>
					<AlertDialogCancel>Cancel</AlertDialogCancel>
					<Button
						disabled={bulk.isPending || noteMissing}
						onClick={() => void run()}
					>
						{bulk.isPending && (
							<Spinner
								aria-label="Recording decisions"
								data-icon="inline-start"
							/>
						)}
						{CHOICE_LABEL[choice]}
					</Button>
				</AlertDialogFooter>
			</AlertDialogContent>
		</AlertDialog>
	);
}

import type { RunSummary } from "@terrasentry/api-client";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { createColumnHelper } from "@tanstack/react-table";
import { Trash2Icon } from "lucide-react";
import { useMemo, useState } from "react";

import { DataTable, type TableFeatureSet } from "#/components/data-table";
import { ErrorState } from "#/components/error-state";
import { PageHeader } from "#/components/page-header";
import { RunStateBadge, VerdictBadge } from "#/components/status-badge";
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
import { Skeleton } from "#/components/ui/skeleton";
import { Spinner } from "#/components/ui/spinner";
import { Tabs, TabsList, TabsTrigger } from "#/components/ui/tabs";
import { useDeleteRun } from "#/features/runs/mutations";
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
		cell: (info) => {
			const run = info.row.original;
			const target =
				run.kind === "batch"
					? { to: "/batch/$batchId" as const, params: { batchId: run.run_id } }
					: { to: "/runs/$runId" as const, params: { runId: run.run_id } };
			return (
				<Link
					{...target}
					className="flex flex-col text-left group"
					onClick={(event) => event.stopPropagation()}
				>
					<span className="font-mono text-xs font-medium text-foreground underline underline-offset-2 hover:text-accent-sunset">
						{info.getValue() ?? run.run_id}
					</span>
					<span className="text-caption-mono-sm text-muted-foreground">
						{run.kind}
					</span>
				</Link>
			);
		},
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
	helper.display({
		id: "delete",
		header: "",
		cell: (info) => <DeleteRunButton run={info.row.original} />,
	}),
]);

/**
 * Per-row delete. Batch parents have no button: the API refuses them, so their records are
 * deleted one at a time. In-flight runs show a disabled button until they finish.
 */
function DeleteRunButton({ run }: { run: RunSummary }) {
	const [open, setOpen] = useState(false);
	const remove = useDeleteRun();
	if (run.kind === "batch") {
		return null;
	}
	const busy = run.state === "queued" || run.state === "running";
	const label = run.record_id ?? run.run_id;
	return (
		<>
			<Button
				variant="ghost"
				size="icon-sm"
				aria-label={`Delete ${label}`}
				title={busy ? "Wait until this run finishes" : "Delete run"}
				disabled={busy}
				onClick={() => setOpen(true)}
			>
				<Trash2Icon />
			</Button>
			<AlertDialog
				open={open}
				onOpenChange={(next) => {
					if (!next) {
						remove.reset();
					}
					setOpen(next);
				}}
			>
				<AlertDialogContent>
					<AlertDialogHeader>
						<AlertDialogTitle>Delete {label}?</AlertDialogTitle>
						<AlertDialogDescription>
							This removes the run with its steps, evidence, verdict, DDS record,
							and SAP action history. The DDS XML and trace files on disk stay.
							This cannot be undone.
						</AlertDialogDescription>
					</AlertDialogHeader>
					{remove.error && <ErrorState error={remove.error} />}
					<AlertDialogFooter>
						<AlertDialogCancel>Cancel</AlertDialogCancel>
						<Button
							variant="destructive"
							disabled={remove.isPending}
							onClick={() =>
								remove.mutate(run.run_id, {
									onSuccess: () => setOpen(false),
								})
							}
						>
							{remove.isPending && (
								<Spinner aria-label="Deleting" data-icon="inline-start" />
							)}
							Delete run
						</Button>
					</AlertDialogFooter>
				</AlertDialogContent>
			</AlertDialog>
		</>
	);
}

function RunsPage() {
	const { kind = "all" } = Route.useSearch();
	const navigate = useNavigate();
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
					void navigate({
						to: "/runs",
						search: { kind: value as string },
						replace: true,
					})
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
					onRowClick={(run) => {
						const destination =
							run.kind === "batch"
								? {
										to: "/batch/$batchId" as const,
										params: { batchId: run.run_id },
									}
								: {
										to: "/runs/$runId" as const,
										params: { runId: run.run_id },
									};
						void navigate(destination).catch((err) => {
							console.error("Navigation failed:", err);
						});
					}}
				/>
			)}
		</div>
	);
}

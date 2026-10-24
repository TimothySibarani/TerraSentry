import { DateTime } from "effect";
import {
	CheckIcon,
	CircleIcon,
	LoaderCircleIcon,
	MinusIcon,
	XIcon,
} from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { Badge } from "#/components/ui/badge";
import { formatDateTime, formatDuration, formatScore } from "#/lib/format";
import { cn } from "#/lib/utils";
import type { AgentRun, AgentStatus } from "./agent-run";

export const STATUS_WORD: Record<AgentStatus, string> = {
	pending: "Pending",
	running: "In progress",
	done: "Completed",
	failed: "Failed",
	retasked: "Re-tasked",
	skipped: "Skipped",
};
export const STATUS_TEXT: Record<AgentStatus, string> = {
	pending: "text-muted-foreground",
	running: "text-accent-breeze",
	done: "text-status-compliant",
	failed: "text-status-risk",
	retasked: "text-status-review",
	skipped: "text-muted-foreground",
};
export function AgentStatusMark({
	status,
	className,
}: {
	status: AgentStatus;
	className?: string;
}) {
	const Icon =
		status === "done"
			? CheckIcon
			: status === "failed"
				? XIcon
				: status === "skipped"
					? MinusIcon
					: status === "running" || status === "retasked"
						? LoaderCircleIcon
						: CircleIcon;
	return (
		<span
			className={cn(
				"inline-flex size-5 shrink-0 items-center justify-center rounded-full motion-safe:transition-colors",
				STATUS_TEXT[status],
				className,
			)}
		>
			<Icon
				key={status}
				aria-hidden="true"
				className={cn(
					"size-3.5 motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in",
					(status === "running" || status === "retasked") &&
						"motion-safe:animate-spin",
				)}
			/>
			<span className="sr-only">{STATUS_WORD[status]}</span>
		</span>
	);
}
export function useRunClock(state: string) {
	const [now, setNow] = useState<number>();
	useEffect(() => {
		if (!["queued", "running", "needs_more_data"].includes(state)) return;
		const tick = () => setNow(DateTime.toEpochMillis(DateTime.nowUnsafe()));
		tick();
		const timer = setInterval(tick, 1000);
		return () => clearInterval(timer);
	}, [state]);
	return now;
}

/** Horizontal run pipeline (todo-list pattern) and the run's models and totals on one line. */
export function RunOverview({
	run,
	score,
	started,
}: {
	run: AgentRun;
	score: number | null;
	started: DateTime.Utc | null;
}) {
	const done = run.stages.filter((stage) => stage.status === "done").length;
	return (
		<section
			aria-label="Run overview"
			className="flex flex-col gap-4 rounded-xl border bg-card p-4"
		>
			<div className="flex items-center justify-between gap-3">
				<h2 className="eyebrow-sm text-muted-foreground">Pipeline</h2>
				<span className="text-caption-mono-sm tabular-nums text-muted-foreground">
					{done}/{run.stages.length} completed
				</span>
			</div>
			<ol
				aria-label="Run pipeline"
				aria-live="polite"
				className="flex flex-wrap items-center gap-y-3"
			>
				{run.stages.map((stage, index) => (
					<li
						key={stage.name}
						className={cn("flex items-center", index > 0 && "flex-1")}
					>
						{index > 0 && (
							<span
								aria-hidden="true"
								className={cn(
									"mx-2 h-px min-w-4 flex-1 motion-safe:transition-colors",
									stage.status === "pending" || stage.status === "skipped"
										? "bg-border"
										: "bg-foreground/40",
								)}
							/>
						)}
						<span
							aria-current={stage.status === "running" ? "step" : undefined}
							className={cn(
								"flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-body-sm whitespace-nowrap motion-safe:transition-colors",
								stage.status === "running" &&
									"border-accent-breeze/50 bg-accent-breeze/10",
								stage.status === "failed" &&
									"border-status-risk/50 bg-status-risk/10",
								(stage.status === "pending" || stage.status === "skipped") &&
									"text-muted-foreground",
							)}
						>
							<AgentStatusMark status={stage.status} />
							{stage.label}
						</span>
					</li>
				))}
			</ol>
			<dl className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t pt-3 text-body-sm">
				{Object.entries(run.config.models).map(([role, model]) => (
					<div key={role} className="flex min-w-0 items-center gap-2">
						<dt className="text-muted-foreground capitalize">{role}</dt>
						<dd className="min-w-0">
							<Badge variant="outline" className="max-w-72 truncate font-mono">
								{model}
							</Badge>
							<span className="sr-only">
								{" "}
								{role} · {model}
							</span>
						</dd>
					</div>
				))}
				<Stat label="Agents">
					{run.totals.agentCount}
					{run.totals.activeCount > 0 && (
						<span className="text-accent-breeze">
							{" "}
							· {run.totals.activeCount} active
						</span>
					)}
				</Stat>
				<Stat label="Tool calls">{run.totals.toolCount}</Stat>
				<Stat label="Tokens">
					{run.config.recorded
						? run.totals.tokens.toLocaleString("en-GB")
						: "—"}
				</Stat>
				<Stat label="Score">{formatScore(score)}</Stat>
				<Stat label="Elapsed">
					{formatDuration(run.totals.wallTimeMs / 1000)}
				</Stat>
				<Stat label="Started">{formatDateTime(started)}</Stat>
			</dl>
		</section>
	);
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
	return (
		<div className="flex items-baseline gap-2">
			<dt className="text-muted-foreground">{label}</dt>
			<dd className="tabular-nums">{children}</dd>
		</div>
	);
}

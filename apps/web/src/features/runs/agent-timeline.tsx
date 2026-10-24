import { ChevronRightIcon } from "lucide-react";
import { type KeyboardEvent, useState } from "react";
import { Badge } from "#/components/ui/badge";
import { formatDuration } from "#/lib/format";
import { cn } from "#/lib/utils";
import {
	type AgentInvocation,
	type AgentRun,
	type AgentToolCall,
	groupTools,
	type RunAgent,
	type ToolGroup,
} from "./agent-run";
import { AgentStatusMark } from "./run-overview";

const LABEL_WIDTH = "16rem";
const TICKS = [0, 0.25, 0.5, 0.75, 1];

/** Arrow keys move between selectable rows; Enter/Space activate as buttons do. */
export function moveSelection(event: KeyboardEvent<HTMLElement>) {
	if (
		!["ArrowDown", "ArrowUp"].includes(event.key) ||
		!(event.target instanceof HTMLButtonElement)
	)
		return;
	const buttons = Array.from(
		event.currentTarget.querySelectorAll<HTMLButtonElement>(
			"button[data-row-select]",
		),
	);
	const index = buttons.indexOf(event.target);
	if (index < 0) return;
	const next = buttons[index + (event.key === "ArrowDown" ? 1 : -1)];
	if (next) {
		event.preventDefault();
		next.focus();
		next.click();
	}
}

const tokens = (value: number) =>
	value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value);
const shortModel = (model: string) =>
	model.replace(/^sap\//, "").replace(/^anthropic--/, "");

/**
 * One timeline: the agent tree is the label column, bars share its rows, and a single
 * playhead crosses every track (agent-trace pattern, no chart library).
 */
export function AgentTimeline({
	run,
	domainStart,
	domainEnd,
	playhead,
	live,
	onScrub,
	onSelect,
	selectedAgent,
	selectedStep,
}: {
	run: AgentRun;
	domainStart: number;
	domainEnd: number;
	playhead: number;
	live: boolean;
	onScrub: (value: number) => void;
	onSelect: (agent: string, step?: string) => void;
	selectedAgent?: string;
	selectedStep?: string;
}) {
	const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
	const duration = Math.max(1, domainEnd - domainStart);
	const pct = (value: number) =>
		Math.min(100, Math.max(0, ((value - domainStart) / duration) * 100));
	const span = (start: number, end: number) => ({
		left: `${pct(start)}%`,
		width: `max(3px, ${pct(end) - pct(start)}%)`,
	});
	const toggle = (name: string) =>
		setCollapsed((previous) => {
			const next = new Set(previous);
			if (next.has(name)) next.delete(name);
			else next.add(name);
			return next;
		});
	const grid = { gridTemplateColumns: `${LABEL_WIDTH} minmax(0, 1fr)` };
	return (
		<section
			aria-label="Agent timeline"
			className="flex min-w-0 flex-col gap-2"
		>
			<div className="flex items-center justify-between gap-2">
				<h3 className="eyebrow-sm text-muted-foreground">
					Agents & tool calls
				</h3>
				<div className="flex items-center gap-2 text-caption-mono-sm tabular-nums text-muted-foreground">
					<Badge variant={live ? "compliant" : "outline"}>
						{live ? "Live" : "Replay"}
					</Badge>
					{formatDuration((playhead - domainStart) / 1000)} /{" "}
					{formatDuration(duration / 1000)}
				</div>
			</div>
			<div className="grid items-center gap-x-3" style={grid}>
				<label
					htmlFor="agent-replay"
					className="text-caption-mono-sm text-muted-foreground"
				>
					{live ? "Following live" : "Drag to replay"}
				</label>
				<input
					id="agent-replay"
					aria-label="Replay time"
					type="range"
					min={domainStart}
					max={Math.max(domainStart + 1, domainEnd)}
					step={1}
					value={playhead}
					disabled={live || domainStart === domainEnd}
					onChange={(event) => onScrub(Number(event.target.value))}
					className="w-full accent-accent-breeze focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50"
				/>
				<span />
				<div
					aria-hidden="true"
					className="relative h-4 text-caption-mono-sm text-muted-foreground"
				>
					{TICKS.map((tick) => (
						<span
							key={tick}
							className={cn(
								"absolute top-0 tabular-nums",
								tick === 0
									? ""
									: tick === 1
										? "-translate-x-full"
										: "-translate-x-1/2",
							)}
							style={{ left: `${tick * 100}%` }}
						>
							+{formatDuration((duration * tick) / 1000)}
						</span>
					))}
				</div>
			</div>
			<div className="relative">
				{/* Grid lines and the playhead live in the track column only. */}
				<div
					aria-hidden="true"
					className="pointer-events-none absolute inset-y-0 right-0"
					style={{ left: `calc(${LABEL_WIDTH} + 0.75rem)` }}
				>
					{TICKS.map((tick) => (
						<span
							key={tick}
							className="absolute inset-y-0 w-px bg-hairline"
							style={{ left: `${tick * 100}%` }}
						/>
					))}
					<span
						className={cn(
							"absolute inset-y-0 z-10 w-px",
							live ? "bg-accent-breeze" : "bg-foreground/70",
						)}
						style={{ left: `${pct(playhead)}%` }}
					/>
				</div>
				<div
					role="tree"
					aria-label="Agents"
					onKeyDown={moveSelection}
					className="relative flex flex-col"
				>
					{run.agents.map((agent) => {
						const groups = agent.invocations.flatMap(groupTools);
						const open = !collapsed.has(agent.name);
						return (
							<div
								key={agent.name}
								role="none"
								className="border-t py-1 first:border-t-0"
							>
								<AgentRow
									agent={agent}
									grid={grid}
									span={span}
									pct={pct}
									playhead={playhead}
									open={open}
									hasChildren={groups.length > 0}
									onToggle={() => toggle(agent.name)}
									selected={selectedAgent === agent.name && !selectedStep}
									onSelect={() => onSelect(agent.name)}
								/>
								{open && groups.length > 0 && (
									<fieldset
										aria-label={`${agent.name} tool calls`}
										className="m-0 min-w-0 border-0 p-0"
									>
										{groups.map((group) => (
											<ToolRow
												key={group.key}
												group={group}
												grid={grid}
												span={span}
												playhead={playhead}
												selectedStep={selectedStep}
												onSelect={(step) => onSelect(agent.name, step)}
												showOrdinal={agent.invocations.length > 1}
											/>
										))}
									</fieldset>
								)}
							</div>
						);
					})}
				</div>
			</div>
			<p className="text-caption-mono-sm text-muted-foreground">
				Arrow keys move between rows. Re-task rounds are drawn in the review
				colour; repeated calls to one tool are grouped.
			</p>
		</section>
	);
}

function AgentRow({
	agent,
	grid,
	span,
	pct,
	playhead,
	open,
	hasChildren,
	onToggle,
	selected,
	onSelect,
}: {
	agent: RunAgent;
	grid: { gridTemplateColumns: string };
	span: (start: number, end: number) => { left: string; width: string };
	pct: (value: number) => number;
	playhead: number;
	open: boolean;
	hasChildren: boolean;
	onToggle: () => void;
	selected: boolean;
	onSelect: () => void;
}) {
	const toolCount = agent.invocations.reduce(
		(sum, item) => sum + item.tools.length,
		0,
	);
	const delegations = agent.invocations.flatMap((item) => item.delegations);
	const meta = [
		agent.role === "code"
			? "deterministic code"
			: delegations.length
				? `${delegations.length} delegations`
				: `${toolCount} tool calls`,
		agent.invocations.length
			? formatDuration(agent.durationMs / 1000)
			: undefined,
		agent.tokens ? `${tokens(agent.tokens)} tok` : undefined,
	].filter(Boolean);
	return (
		<div className="grid items-center gap-x-3" style={grid}>
			<div className="flex min-w-0 items-center">
				<button
					type="button"
					aria-label={open ? `Collapse ${agent.name}` : `Expand ${agent.name}`}
					aria-expanded={open}
					disabled={!hasChildren}
					onClick={onToggle}
					className="flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:text-foreground disabled:invisible"
				>
					<ChevronRightIcon
						aria-hidden="true"
						className={cn(
							"size-3.5 motion-safe:transition-transform",
							open && "rotate-90",
						)}
					/>
				</button>
				<button
					type="button"
					role="treeitem"
					aria-selected={selected}
					aria-expanded={hasChildren ? open : undefined}
					data-row-select
					onClick={onSelect}
					className={cn(
						"flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1 text-left outline-none hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring/50",
						selected && "bg-muted",
					)}
				>
					<AgentStatusMark status={agent.status} />
					<span className="flex min-w-0 flex-col">
						<span className="flex min-w-0 items-center gap-1.5">
							<span className="truncate text-body-sm">
								{agent.name.replaceAll("_", " ")}
							</span>
							{agent.invocations.length > 1 && (
								<Badge variant="review">×{agent.invocations.length}</Badge>
							)}
						</span>
						<span
							className="truncate text-xs text-muted-foreground"
							title={agent.model}
						>
							{agent.role === "code" ? "code" : shortModel(agent.model)} ·{" "}
							{meta.join(" · ")}
						</span>
					</span>
				</button>
			</div>
			<div className="relative h-7 rounded-sm bg-muted/30">
				{agent.invocations.map((invocation) => (
					<InvocationBar
						key={invocation.ordinal}
						agent={agent}
						invocation={invocation}
						style={span(invocation.start, invocation.end ?? playhead)}
						onSelect={onSelect}
					/>
				))}
				{agent.invocations
					.flatMap((item) => item.delegations)
					.map((delegation) => (
						<span
							key={`${delegation.agent}-${delegation.ordinal}`}
							aria-hidden="true"
							title={`delegated to ${delegation.agent}${delegation.ordinal > 1 ? " (re-task)" : ""}`}
							className={cn(
								"absolute top-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rotate-45 bg-foreground",
								delegation.ordinal > 1 && "bg-status-review",
							)}
							style={{ left: `${pct(delegation.at)}%` }}
						/>
					))}
			</div>
		</div>
	);
}

function InvocationBar({
	agent,
	invocation,
	style,
	onSelect,
}: {
	agent: RunAgent;
	invocation: AgentInvocation;
	style: { left: string; width: string };
	onSelect: () => void;
}) {
	const running = invocation.end === undefined;
	return (
		<button
			type="button"
			tabIndex={-1}
			aria-label={`${agent.name} invocation ${invocation.ordinal}`}
			onClick={onSelect}
			style={style}
			className={cn(
				"absolute inset-y-1 rounded-sm border motion-safe:transition-[width,left] motion-safe:duration-300",
				invocation.failed
					? "border-status-risk/70 bg-status-risk/40"
					: running
						? "border-accent-breeze/70 bg-accent-breeze/30 motion-safe:animate-progress"
						: invocation.ordinal > 1
							? "border-status-review/60 bg-status-review/30"
							: agent.role === "code"
								? "border-outline-on-dark bg-foreground/30"
								: "border-status-compliant/50 bg-status-compliant/25",
			)}
		>
			<span className="sr-only">
				{running ? "Running" : invocation.failed ? "Failed" : "Finished"}
			</span>
		</button>
	);
}

function ToolRow({
	group,
	grid,
	span,
	playhead,
	selectedStep,
	onSelect,
	showOrdinal,
}: {
	group: ToolGroup;
	grid: { gridTemplateColumns: string };
	span: (start: number, end: number) => { left: string; width: string };
	playhead: number;
	selectedStep?: string;
	onSelect: (step: string) => void;
	showOrdinal: boolean;
}) {
	const selected = group.calls.some(
		(call) => call.step.step_id === selectedStep,
	);
	const total = group.calls.reduce((sum, call) => sum + call.durationMs, 0);
	const target =
		group.calls.find((call) => call.step.step_id === selectedStep) ??
		group.calls[0];
	return (
		<div className="grid items-center gap-x-3" style={grid}>
			<button
				type="button"
				role="treeitem"
				aria-selected={selected}
				aria-label={`${group.name}${group.calls.length > 1 ? ` ×${group.calls.length}` : ""}`}
				data-row-select
				onClick={() => target && onSelect(target.step.step_id)}
				className={cn(
					"ml-7 flex min-w-0 items-center gap-2 rounded-md px-1.5 py-0.5 text-left outline-none hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring/50",
					selected && "bg-muted",
				)}
			>
				<ToolDot status={group.status} />
				<span className="truncate font-mono text-xs" title={group.name}>
					{group.name}
				</span>
				{group.calls.length > 1 && (
					<span className="shrink-0 text-xs text-muted-foreground">
						×{group.calls.length}
					</span>
				)}
				{showOrdinal && (
					<span className="shrink-0 text-xs text-muted-foreground">
						r{group.ordinal}
					</span>
				)}
				<span className="ml-auto shrink-0 text-xs tabular-nums text-muted-foreground">
					{group.status === "running" ? "…" : formatDuration(total / 1000)}
				</span>
			</button>
			<div className="relative h-5">
				{group.calls.map((call) => (
					<ToolMark
						key={call.step.step_id}
						call={call}
						style={span(call.start, call.end ?? playhead)}
						selected={call.step.step_id === selectedStep}
						onSelect={() => onSelect(call.step.step_id)}
					/>
				))}
			</div>
		</div>
	);
}

function ToolMark({
	call,
	style,
	selected,
	onSelect,
}: {
	call: AgentToolCall;
	style: { left: string; width: string };
	selected: boolean;
	onSelect: () => void;
}) {
	return (
		<button
			type="button"
			tabIndex={-1}
			aria-label={`${call.step.name} span`}
			onClick={onSelect}
			style={style}
			className={cn(
				"absolute inset-y-1 rounded-[2px] motion-safe:transition-[width] motion-safe:duration-300",
				call.status === "error"
					? "bg-status-risk/70"
					: call.status === "running"
						? "bg-accent-breeze/60 motion-safe:animate-progress"
						: "bg-status-compliant/60",
				selected && "ring-2 ring-foreground",
			)}
		/>
	);
}

function ToolDot({ status }: { status: AgentToolCall["status"] }) {
	return (
		<span
			className={cn(
				"size-1.5 shrink-0 rounded-full",
				status === "error"
					? "bg-status-risk"
					: status === "running"
						? "bg-accent-breeze motion-safe:animate-pulse"
						: "bg-status-compliant",
			)}
		>
			<span className="sr-only">
				{status === "running" ? "Running" : status}
			</span>
		</span>
	);
}

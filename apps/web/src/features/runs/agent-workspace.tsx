import type { TraceStep } from "@terrasentry/api-client";
import { useEffect, useState } from "react";
import {
	Sheet,
	SheetContent,
	SheetHeader,
	SheetTitle,
} from "#/components/ui/sheet";
import { ToggleGroup, ToggleGroupItem } from "#/components/ui/toggle-group";
import { AgentInspector } from "./agent-inspector";
import {
	type AgentRun,
	deriveAgentRun,
	findToolCall,
	focusAgent,
	stepTime,
} from "./agent-run";
import { AgentTimeline } from "./agent-timeline";
import { TracePanel } from "./trace-panel";
import type { RunStreamStatus } from "./use-run-stream";
import { WorkContext } from "./work-context-panel";

const WIDE = "(min-width: 1280px)";

export function AgentWorkspace({
	steps,
	run,
	model,
	state,
	status,
	error,
	onReconnect,
	selectedAgent,
	selectedStep,
	onSelect,
	onOpenMap,
	record = {},
}: {
	steps: readonly TraceStep[];
	run: AgentRun;
	model: string;
	state: string;
	status: RunStreamStatus;
	error?: unknown;
	onReconnect?: () => void;
	selectedAgent?: string;
	selectedStep?: string;
	onSelect: (agent: string, step?: string) => void;
	onOpenMap?: () => void;
	record?: {
		record_id?: string | null;
		supplier_id?: string | null;
		polygon_id?: string | null;
		verification?: { challenges?: readonly unknown[] } | null;
	};
}) {
	const [view, setView] = useState("workspace");
	const [position, setPosition] = useState<number>();
	const [wide, setWide] = useState(true);
	const [inspectorOpen, setInspectorOpen] = useState(false);
	useEffect(() => {
		const query = window.matchMedia(WIDE);
		const update = () => setWide(query.matches);
		update();
		query.addEventListener("change", update);
		return () => query.removeEventListener("change", update);
	}, []);
	const live = ["queued", "running", "needs_more_data"].includes(state);
	const playhead = live
		? run.end
		: Math.min(run.end, Math.max(run.start, position ?? run.end));
	const replaying = !live && playhead < run.end;
	const visibleSteps = replaying
		? steps.filter((step) => stepTime(step) <= playhead)
		: steps;
	const replayState = replaying
		? (visibleSteps.filter((step) => step.kind === "state").at(-1)?.name ??
			"running")
		: state;
	const derived = replaying
		? deriveAgentRun(visibleSteps, {
				model,
				state: replayState,
				now: playhead,
				verification: record.verification,
			})
		: run;
	// Keep future agents listed during replay, but never expose their future tools or output.
	const current: AgentRun = {
		...derived,
		agents: run.agents.map(
			(agent) =>
				derived.agents.find((item) => item.name === agent.name) ?? {
					...agent,
					status: "pending",
					invocations: [],
					tokens: 0,
					durationMs: 0,
				},
		),
	};
	// With nothing selected, look at what matters for this state: the active, failed or last agent.
	const selected =
		findToolCall(current, selectedStep)?.agent ??
		current.agents.find((agent) => agent.name === selectedAgent) ??
		focusAgent(current);
	const select = (agent: string, step?: string) => {
		onSelect(agent, step);
		setInspectorOpen(true);
	};
	const inspector = selected && (
		<AgentInspector
			key={selected.name}
			agent={selected}
			run={current}
			selectedStep={selectedStep}
			playhead={playhead}
			onSelect={select}
		/>
	);
	return (
		<div className="flex flex-col gap-5">
			<div className="flex flex-wrap items-center justify-between gap-3">
				<ToggleGroup
					aria-label="Trace view"
					value={[view]}
					onValueChange={(values) => {
						const value = values[0];
						if (value) setView(value);
					}}
					variant="outline"
					size="sm"
				>
					<ToggleGroupItem value="workspace">Workspace</ToggleGroupItem>
					<ToggleGroupItem value="log">Log</ToggleGroupItem>
				</ToggleGroup>
				<p className="text-caption-mono-sm text-muted-foreground">
					{live ? "Following live agents" : `${steps.length} recorded steps`}
				</p>
			</div>
			{view === "log" || steps.length === 0 || status === "error" ? (
				<TracePanel
					steps={steps}
					status={status}
					error={error}
					onReconnect={onReconnect}
				/>
			) : (
				<>
					<WorkContext
						run={current}
						fallback={record}
						onSelect={select}
						onOpenMap={onOpenMap}
					/>
					<div className="grid min-w-0 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_26rem]">
						<AgentTimeline
							run={current}
							domainStart={run.start}
							domainEnd={run.end}
							playhead={playhead}
							live={live}
							onScrub={setPosition}
							onSelect={select}
							selectedAgent={selected?.name}
							selectedStep={selectedStep}
						/>
						{inspector &&
							(wide ? (
								<div className="sticky top-4 max-h-[calc(100vh-2rem)] min-w-0 overflow-y-auto rounded-xl border bg-card p-4">
									{inspector}
								</div>
							) : (
								<Sheet open={inspectorOpen} onOpenChange={setInspectorOpen}>
									<SheetContent className="w-full overflow-y-auto sm:max-w-lg motion-reduce:transform-none motion-reduce:transition-none">
										<SheetHeader>
											<SheetTitle>Agent inspector</SheetTitle>
										</SheetHeader>
										<div className="px-5 pb-5">{inspector}</div>
									</SheetContent>
								</Sheet>
							))}
					</div>
				</>
			)}
		</div>
	);
}

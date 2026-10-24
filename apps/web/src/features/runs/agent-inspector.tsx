import { Option, Schema } from "effect";
import { Markdown } from "#/components/markdown";
import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import {
	Collapsible,
	CollapsibleContent,
	CollapsibleTrigger,
} from "#/components/ui/collapsible";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "#/components/ui/tabs";
import { formatDuration } from "#/lib/format";
import { cn } from "#/lib/utils";
import {
	type AgentRun,
	type AgentToolCall,
	groupTools,
	type RunAgent,
	tracePayload,
} from "./agent-run";
import { AgentStatusMark, STATUS_TEXT, STATUS_WORD } from "./run-overview";
import { JsonBlock, ToolResultView } from "./tool-result-view";

const Truncated = Schema.Struct({ truncated: Schema.Boolean });

export function AgentInspector({
	agent,
	run,
	selectedStep,
	playhead,
	onSelect,
}: {
	agent: RunAgent;
	run: AgentRun;
	selectedStep?: string;
	playhead: number;
	onSelect: (agent: string, step?: string) => void;
}) {
	const allTools = agent.invocations.flatMap((item) => item.tools);
	const selectedCall = allTools.find(
		(tool) => tool.step.step_id === selectedStep,
	);
	const thoughts = agent.invocations.flatMap((item) => item.thoughts);
	const latest = agent.invocations.at(-1);
	const challenges = agent.invocations.flatMap((item) => item.challenges);
	const activeTool = latest?.tools.find((tool) => tool.status === "running");
	return (
		<section
			aria-label={`${agent.name} inspector`}
			className="flex min-w-0 flex-col gap-3"
		>
			<header className="flex flex-col gap-1">
				<div className="flex flex-wrap items-center gap-2">
					<AgentStatusMark status={agent.status} />
					<h3 className="text-body-sm">{agent.name.replaceAll("_", " ")}</h3>
					<Badge variant="outline">{agent.role}</Badge>
					{agent.invocations.length > 1 && (
						<Badge variant="review">
							re-tasked ×{agent.invocations.length - 1}
						</Badge>
					)}
				</div>
				<p
					aria-live="polite"
					className={cn("text-caption-mono-sm", STATUS_TEXT[agent.status])}
				>
					{STATUS_WORD[agent.status]}
					{latest && agent.status !== "pending"
						? ` · ${formatDuration(((latest.end ?? playhead) - latest.start) / 1000)}`
						: ""}
					{activeTool ? ` · calling ${activeTool.step.name}` : ""}
					{agent.tokens
						? ` · ${agent.tokens.toLocaleString("en-GB")} tokens`
						: ""}
				</p>
			</header>
			<Tabs
				key={`${agent.name}-${selectedStep ?? ""}`}
				defaultValue={selectedCall ? "tools" : "summary"}
			>
				<TabsList variant="line" className="w-full justify-start">
					<TabsTrigger value="summary">Summary</TabsTrigger>
					<TabsTrigger value="tools">
						Tools{allTools.length ? ` (${allTools.length})` : ""}
					</TabsTrigger>
					<TabsTrigger value="thinking">
						Thinking{thoughts.length ? ` (${thoughts.length})` : ""}
					</TabsTrigger>
					<TabsTrigger value="context">Context</TabsTrigger>
				</TabsList>

				<TabsContent value="summary" className="flex flex-col gap-4 pt-3">
					{challenges.length > 0 && (
						<div className="flex flex-col gap-2 rounded-lg border border-status-risk/40 bg-status-risk/5 p-3">
							<p className="text-body-sm text-status-risk">
								{challenges.length} verification challenge(s)
							</p>
							<ul className="flex flex-col gap-2">
								{challenges.map((challenge, index) => (
									<li
										// biome-ignore lint/suspicious/noArrayIndexKey: challenges have no id and never reorder
										key={index}
										className="flex flex-col gap-1 text-body-sm"
									>
										<span className="flex items-center gap-2">
											<Badge
												variant={
													challenge.severity === "error" ? "risk" : "review"
												}
											>
												{challenge.severity}
											</Badge>
											<span className="font-mono text-xs">
												{challenge.kind}
											</span>
										</span>
										<span className="text-muted-foreground">
											{challenge.detail}
										</span>
									</li>
								))}
							</ul>
						</div>
					)}
					{agent.invocations.length === 0 ? (
						<p className="text-body-sm text-muted-foreground">
							{agent.status === "skipped"
								? "This agent did not run: the pipeline stopped before it."
								: "Waiting to be delegated."}
						</p>
					) : (
						agent.invocations.map((item) => (
							<article key={item.ordinal} className="flex flex-col gap-2">
								<h4 className="eyebrow-sm text-muted-foreground">
									{agent.invocations.length > 1
										? `Round ${item.ordinal} · `
										: ""}
									{item.ordinal > 1 ? "Re-task instruction" : "Instruction"}
								</h4>
								<JsonBlock value={item.input} />
								<h4 className="eyebrow-sm text-muted-foreground">Output</h4>
								{item.end === undefined ? (
									<p className="text-body-sm text-accent-breeze motion-safe:animate-pulse">
										Working…
									</p>
								) : item.report && item.report !== "finished" ? (
									<div className="rounded-md bg-canvas-soft p-3 text-body-sm">
										<Markdown content={item.report} />
									</div>
								) : (
									<p className="text-body-sm text-muted-foreground">
										No written output.
									</p>
								)}
								{item.usage && (
									<p className="text-caption-mono-sm text-muted-foreground">
										{item.usage.inputTokens.toLocaleString("en-GB")} in ·{" "}
										{item.usage.outputTokens.toLocaleString("en-GB")} out
									</p>
								)}
							</article>
						))
					)}
				</TabsContent>

				<TabsContent value="tools" className="flex flex-col gap-4 pt-3">
					{allTools.length === 0 ? (
						<p className="text-body-sm text-muted-foreground">
							{agent.role === "code"
								? "Deterministic code node: it calls no tools."
								: "No tool calls recorded at this point."}
						</p>
					) : (
						<>
							<ul aria-label="Tool calls" className="flex flex-col gap-1">
								{agent.invocations.flatMap(groupTools).map((group) => (
									<li
										key={group.key}
										className="flex flex-wrap items-center gap-1"
									>
										<span className="mr-1 font-mono text-xs">{group.name}</span>
										{group.calls.map((call, index) => (
											<Button
												key={call.step.step_id}
												size="xs"
												variant={
													call.step.step_id === selectedStep
														? "secondary"
														: "ghost"
												}
												aria-pressed={call.step.step_id === selectedStep}
												onClick={() => onSelect(agent.name, call.step.step_id)}
												className={cn(
													call.status === "error" && "text-status-risk",
													call.status === "running" && "text-accent-breeze",
												)}
											>
												{group.calls.length > 1 ? `#${index + 1}` : "open"}
											</Button>
										))}
									</li>
								))}
							</ul>
							<ToolCallDetail call={selectedCall ?? allTools[0]} />
						</>
					)}
				</TabsContent>

				<TabsContent value="thinking" className="flex flex-col gap-3 pt-3">
					{thoughts.length ? (
						thoughts.map((step) => {
							const payload = tracePayload(step);
							return (
								<div key={step.step_id} className="flex flex-col gap-1">
									<p className="text-caption-mono-sm text-muted-foreground">
										{payload.reasoning ? "Model reasoning" : "Agent note"}
									</p>
									{payload.reasoning && <JsonBlock value={payload.reasoning} />}
									{payload.text && (
										<div className="rounded-md bg-canvas-soft p-3 text-body-sm">
											<Markdown content={payload.text} />
										</div>
									)}
									{payload.truncated && (
										<p className="text-xs text-muted-foreground">
											Truncated to 2 KB.
										</p>
									)}
								</div>
							);
						})
					) : (
						<p className="text-body-sm text-muted-foreground">
							No thinking was recorded for this agent. Models only show
							reasoning when they emit it (set AGENT_REASONING_EFFORT for the
							orchestrator); scripted runs emit none.
						</p>
					)}
				</TabsContent>

				<TabsContent
					value="context"
					className="flex flex-col gap-3 pt-3 text-body-sm"
				>
					{!run.config.recorded && (
						<p className="text-muted-foreground">
							Configuration was not recorded for this run.
						</p>
					)}
					<dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1">
						<dt className="text-muted-foreground">Model</dt>
						<dd className="break-words font-mono text-xs leading-5">
							{agent.model}
						</dd>
						{agent.role !== "code" &&
							Object.entries(run.config.params[agent.role] ?? {}).map(
								([key, value]) => (
									<div key={key} className="contents">
										<dt className="text-muted-foreground">{key}</dt>
										<dd className="font-mono text-xs leading-5">
											{String(value)}
										</dd>
									</div>
								),
							)}
					</dl>
					{agent.role === "code" ? (
						<p className="text-muted-foreground">
							Deterministic code node. The rubric and the DDS writer run in
							code, not in a model.
						</p>
					) : (
						<>
							<p className="text-muted-foreground">Tools available</p>
							<ul className="flex flex-wrap gap-1">
								{agent.tools.map((tool) => (
									<li key={tool}>
										<Badge variant="outline" className="font-mono">
											{tool}
										</Badge>
									</li>
								))}
							</ul>
							<Collapsible>
								<CollapsibleTrigger
									render={<Button variant="outline" size="sm" />}
								>
									System prompt
								</CollapsibleTrigger>
								<CollapsibleContent className="pt-2">
									<JsonBlock value={agent.systemPrompt ?? undefined} />
								</CollapsibleContent>
							</Collapsible>
						</>
					)}
				</TabsContent>
			</Tabs>
		</section>
	);
}

function ToolCallDetail({ call }: { call: AgentToolCall | undefined }) {
	if (!call) return null;
	const truncated = Option.exists(
		Schema.decodeUnknownOption(Truncated)(call.result),
		(value) => value.truncated,
	);
	return (
		<article className="flex flex-col gap-3 rounded-lg border p-3 motion-safe:animate-in motion-safe:fade-in">
			<header className="flex flex-wrap items-center gap-2">
				<h4 className="font-mono text-xs">{call.step.name}</h4>
				<Badge
					variant={
						call.status === "error"
							? "risk"
							: call.status === "running"
								? "outline"
								: "compliant"
					}
				>
					{call.status}
				</Badge>
				<span className="ml-auto text-caption-mono-sm text-muted-foreground">
					{call.status === "running"
						? "in flight"
						: formatDuration(call.durationMs / 1000)}{" "}
					· {call.step.step_id}
				</span>
			</header>
			<div className="flex flex-col gap-1">
				<p className="eyebrow-sm text-muted-foreground">Input</p>
				<JsonBlock value={call.input} />
			</div>
			<div className="flex flex-col gap-1">
				<p className="eyebrow-sm text-muted-foreground">Result</p>
				{call.status === "running" ? (
					<p className="text-body-sm text-accent-breeze motion-safe:animate-pulse">
						Waiting for the source…
					</p>
				) : (
					<ToolResultView name={call.step.name} result={call.result} />
				)}
				{truncated && (
					<p className="text-body-sm text-status-review">
						Result truncated to 4 KB. The model received the full result.
					</p>
				)}
			</div>
			{call.status !== "running" && call.result !== undefined && (
				<Collapsible>
					<CollapsibleTrigger render={<Button variant="ghost" size="xs" />}>
						Raw result
					</CollapsibleTrigger>
					<CollapsibleContent className="pt-2">
						<JsonBlock value={call.result} />
					</CollapsibleContent>
				</Collapsible>
			)}
		</article>
	);
}

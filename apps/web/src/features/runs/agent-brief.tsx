import type { TraceStep } from "@terrasentry/api-client";
import { BotIcon, FileTextIcon, SparklesIcon } from "lucide-react";
import { useState } from "react";

import { Markdown } from "#/components/markdown";
import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import {
	Card,
	CardAction,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "#/components/ui/card";
import { Skeleton } from "#/components/ui/skeleton";
import { cn } from "#/lib/utils";
import { simplifyAgentBrief } from "./simplify-agent-brief";

/** Specialist reports the agents wrote during the run, in trace order. */
export function specialistReports(
	steps: ReadonlyArray<TraceStep>,
): ReadonlyArray<TraceStep> {
	return steps.filter((step) => step.kind === "report");
}

/**
 * The supervisor's written summary of the evidence. It helps a person decide, but it is
 * never the verdict: the rubric alone scores the run.
 */
export function AgentBrief({
	summary,
	model,
	steps,
}: {
	summary: string;
	model: string;
	steps: ReadonlyArray<TraceStep>;
}) {
	const [simplified, setSimplified] = useState(false);
	const [isSimplifying, setIsSimplifying] = useState(false);

	if (model === "deterministic" || summary.trim() === "") {
		return null;
	}

	const handleToggle = () => {
		if (simplified) {
			setSimplified(false);
			setIsSimplifying(false);
			return;
		}

		setIsSimplifying(true);
		setTimeout(() => {
			setSimplified(true);
			setIsSimplifying(false);
		}, 750);
	};

	const reports = specialistReports(steps);
	return (
		<Card
			size="sm"
			className={cn(
				"transition-all duration-300",
				isSimplifying && "border-accent-sunset/50 ring-1 ring-accent-sunset/30",
			)}
		>
			<CardHeader>
				<CardTitle className="flex flex-wrap items-center gap-2">
					<BotIcon aria-hidden="true" className="size-3.5" />
					Agent brief
					<Badge variant="outline">{model}</Badge>
					{isSimplifying ? (
						<Badge
							variant="secondary"
							className="gap-1.5 border border-accent-sunset/40 bg-accent-sunset/10 text-accent-sunset animate-breathe"
						>
							<span className="relative flex size-2">
								<span className="absolute inline-flex size-full animate-ping rounded-full bg-accent-sunset opacity-75" />
								<span className="relative inline-flex size-2 rounded-full bg-accent-sunset" />
							</span>
							Simplifying…
						</Badge>
					) : simplified ? (
						<Badge
							variant="secondary"
							className="gap-1.5 border border-status-compliant/40 bg-status-compliant/10 text-status-compliant"
						>
							<span className="relative flex size-2">
								<span className="absolute inline-flex size-full animate-ping rounded-full bg-status-compliant opacity-75" />
								<span className="relative inline-flex size-2 rounded-full bg-status-compliant" />
							</span>
							Public view
						</Badge>
					) : null}
				</CardTitle>
				<CardDescription>
					{isSimplifying
						? "Simplifying complex EUDR telemetry into plain language for public understanding…"
						: simplified
							? "Plain-language summary of evidence for the public. Context only: the rubric decides the verdict."
							: "Written by the agents from the evidence. Context only: the rubric decides the verdict."}
				</CardDescription>
				<CardAction>
					<Button
						type="button"
						variant={simplified ? "secondary" : "outline"}
						size="sm"
						disabled={isSimplifying}
						onClick={handleToggle}
						className={cn(
							"transition-all",
							isSimplifying &&
								"border-accent-sunset/40 text-accent-sunset animate-pulse",
						)}
					>
						{isSimplifying ? (
							<>
								<SparklesIcon
									data-icon="inline-start"
									aria-hidden="true"
									className="animate-spin text-accent-sunset"
								/>
								Simplifying…
							</>
						) : simplified ? (
							<>
								<FileTextIcon data-icon="inline-start" aria-hidden="true" />
								Technical brief
							</>
						) : (
							<>
								<SparklesIcon data-icon="inline-start" aria-hidden="true" />
								Simplify for public
							</>
						)}
					</Button>
				</CardAction>
			</CardHeader>
			<CardContent className="flex flex-col gap-3 text-body-sm">
				{isSimplifying ? (
					<div
						data-testid="breathing-simplifying"
						className="flex flex-col gap-3 rounded-lg border border-accent-sunset/30 bg-accent-sunset/5 p-4 animate-breathe"
					>
						<div className="flex items-center gap-2 font-medium text-accent-sunset">
							<SparklesIcon
								aria-hidden="true"
								className="size-4 animate-spin"
							/>
							<span>Translating technical evidence into plain language…</span>
						</div>
						<p className="text-body-sm text-muted-foreground">
							Analyzing deforestation satellite records, concession boundaries,
							and peat moratorium rules for clear public presentation.
						</p>
						<div className="space-y-2 pt-1">
							<Skeleton className="h-3.5 w-4/5 bg-accent-sunset/15" />
							<Skeleton className="h-3.5 w-full bg-accent-sunset/15" />
							<Skeleton className="h-3.5 w-2/3 bg-accent-sunset/15" />
						</div>
					</div>
				) : (
					<div className={cn(simplified && "animate-in fade-in duration-300")}>
						<Markdown
							content={simplified ? simplifyAgentBrief(summary) : summary}
						/>
					</div>
				)}
				{model === "scripted" && (
					<p className="text-caption-mono-sm text-muted-foreground">
						Scripted replay: this summary is canned, not written by a model.
					</p>
				)}
				{reports.length > 0 && (
					<p className="text-caption-mono-sm text-muted-foreground">
						{reports.length} specialist report
						{reports.length === 1 ? "" : "s"} in the trace
					</p>
				)}
			</CardContent>
		</Card>
	);
}

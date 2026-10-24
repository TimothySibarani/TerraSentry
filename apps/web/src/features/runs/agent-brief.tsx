import type { TraceStep } from "@terrasentry/api-client";
import { BotIcon } from "lucide-react";

import { Badge } from "#/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "#/components/ui/card";

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
	if (model === "deterministic" || summary.trim() === "") {
		return null;
	}
	const reports = specialistReports(steps);
	return (
		<Card size="sm">
			<CardHeader>
				<CardTitle className="flex flex-wrap items-center gap-2">
					<BotIcon aria-hidden="true" className="size-3.5" />
					Agent brief
					<Badge variant="outline">{model}</Badge>
				</CardTitle>
				<CardDescription>
					Written by the agents from the evidence. Context only: the rubric
					decides the verdict.
				</CardDescription>
			</CardHeader>
			<CardContent className="flex flex-col gap-2 text-body-sm">
				<p className="whitespace-pre-wrap text-foreground">{summary}</p>
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

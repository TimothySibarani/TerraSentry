import type { BatchMode } from "@terrasentry/api-client";

import { Badge } from "#/components/ui/badge";

/** What a batch actually ran: the rubric screening path, or per-record agents on a model. */
export function batchModeLabel(mode: BatchMode, model: string | null): string {
	return mode === "agent"
		? `Agent · ${model ?? "unknown model"}`
		: "Fast screening";
}

export function BatchModeBadge({
	mode,
	model,
}: {
	mode: BatchMode;
	model: string | null;
}) {
	return (
		<Badge variant={mode === "agent" ? "review" : "outline"}>
			{batchModeLabel(mode, model)}
		</Badge>
	);
}

/** Explains why the design match can differ from the record count. */
export function labelledNote(unlabelledCount: number): string {
	return unlabelledCount > 0
		? `Labelled records only · ${unlabelledCount} unlabelled excluded`
		: "Labelled records only";
}

import { Badge } from "#/components/ui/badge";
import { Spinner } from "#/components/ui/spinner";

type BadgeVariant =
	| "outline"
	| "secondary"
	| "risk"
	| "review"
	| "compliant"
	| "destructive";

const RUN_STATE: Record<
	string,
	{ label: string; variant: BadgeVariant; pending?: boolean }
> = {
	queued: { label: "Queued", variant: "outline" },
	running: { label: "Running", variant: "secondary", pending: true },
	needs_more_data: { label: "Needs data", variant: "risk" },
	awaiting_review: { label: "Awaiting review", variant: "review" },
	complete: { label: "Complete", variant: "compliant" },
	failed: { label: "Failed", variant: "destructive" },
};

const VERDICT: Record<string, { label: string; variant: BadgeVariant }> = {
	compliant: { label: "Compliant", variant: "compliant" },
	high_risk: { label: "High risk", variant: "risk" },
	ambiguous: { label: "Ambiguous", variant: "review" },
};

export function RunStateBadge({ state }: { state: string }) {
	const spec = RUN_STATE[state] ?? {
		label: state,
		variant: "outline" as const,
	};
	return (
		<Badge variant={spec.variant}>
			{spec.pending && <Spinner aria-label="In progress" />}
			{spec.label}
		</Badge>
	);
}

export function VerdictBadge({
	verdict,
}: {
	verdict: string | null | undefined;
}) {
	if (!verdict) {
		return <span className="text-body-sm text-muted-foreground">—</span>;
	}
	const spec = VERDICT[verdict] ?? {
		label: verdict,
		variant: "outline" as const,
	};
	return <Badge variant={spec.variant}>{spec.label}</Badge>;
}

export function RiskLevelBadge({
	level,
}: {
	level: string | null | undefined;
}) {
	if (!level) {
		return <span className="text-body-sm text-muted-foreground">—</span>;
	}
	const nonNegligible = level === "non_negligible";
	return (
		<Badge variant={nonNegligible ? "risk" : "compliant"}>
			{nonNegligible ? "Non-negligible" : "Negligible"}
		</Badge>
	);
}

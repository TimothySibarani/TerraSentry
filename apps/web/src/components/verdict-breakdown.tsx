import { cn } from "#/lib/utils";

const ORDER = ["compliant", "high_risk", "ambiguous"] as const;

const TONE: Record<string, { label: string; bar: string; dot: string }> = {
	compliant: {
		label: "Compliant",
		bar: "bg-status-compliant",
		dot: "bg-status-compliant",
	},
	high_risk: {
		label: "High risk",
		bar: "bg-status-risk",
		dot: "bg-status-risk",
	},
	ambiguous: {
		label: "Ambiguous",
		bar: "bg-status-review",
		dot: "bg-status-review",
	},
};

export function VerdictBreakdown({
	verdicts,
	expected,
	total,
	className,
}: {
	verdicts: Record<string, number>;
	expected?: Record<string, number>;
	total?: number;
	className?: string;
}) {
	const sum =
		total ?? ORDER.reduce((acc, key) => acc + (verdicts[key] ?? 0), 0);

	return (
		<div className={cn("flex flex-col gap-3", className)}>
			<div
				className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted"
				role="img"
				aria-label={ORDER.map(
					(key) => `${TONE[key].label}: ${verdicts[key] ?? 0}`,
				).join(", ")}
			>
				{ORDER.map((key) => {
					const value = verdicts[key] ?? 0;
					if (value === 0 || sum === 0) {
						return null;
					}
					return (
						<div
							key={key}
							className={cn("h-full", TONE[key].bar)}
							style={{ width: `${(value / sum) * 100}%` }}
						/>
					);
				})}
			</div>
			<ul className="flex flex-wrap gap-x-6 gap-y-1">
				{ORDER.map((key) => (
					<li key={key} className="flex items-center gap-2 text-body-sm">
						<span
							aria-hidden="true"
							className={cn("size-2 rounded-full", TONE[key].dot)}
						/>
						<span className="text-muted-foreground">{TONE[key].label}</span>
						<span className="tabular-nums text-foreground">
							{verdicts[key] ?? 0}
						</span>
						{expected && (
							<span className="text-caption-mono-sm text-muted-foreground">
								/ {expected[key] ?? 0} expected
							</span>
						)}
					</li>
				))}
			</ul>
		</div>
	);
}

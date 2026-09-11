import type {
	Assessment,
	VerificationReport,
	VerdictOut,
} from "@terrasentry/api-client";
import { AlertTriangleIcon, CheckCircle2Icon } from "lucide-react";

import { RiskLevelBadge, VerdictBadge } from "#/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "#/components/ui/alert";
import { Badge } from "#/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "#/components/ui/card";
import { Separator } from "#/components/ui/separator";
import { formatNumber } from "#/lib/format";

const LEVEL_VARIANT: Record<string, "compliant" | "review" | "risk"> = {
	clear: "compliant",
	borderline: "review",
	flag: "risk",
};

const SEVERITY_VARIANT: Record<string, "outline" | "review" | "risk"> = {
	info: "outline",
	warning: "review",
	error: "risk",
};

function FindingsList({ assessment }: { assessment: Assessment }) {
	if (assessment.findings.length === 0) {
		return (
			<p className="text-body-sm text-muted-foreground">
				No findings recorded for this assessment.
			</p>
		);
	}
	return (
		<ul className="flex flex-col gap-3">
			{assessment.findings.map((finding) => (
				<li
					key={finding.code}
					className="flex flex-col gap-1.5 rounded-md border border-border p-3"
				>
					<div className="flex flex-wrap items-center gap-2">
						<span className="text-body-sm text-foreground">
							{finding.code.replaceAll("_", " ")}
						</span>
						<Badge variant={LEVEL_VARIANT[finding.level] ?? "outline"}>
							{finding.level}
						</Badge>
						<span className="text-caption-mono-sm text-muted-foreground tabular-nums">
							{finding.points} pts
						</span>
						{finding.mitigating && (
							<Badge variant="secondary">mitigating</Badge>
						)}
						<span className="ml-auto text-caption-mono-sm text-muted-foreground">
							{finding.evidence_ids.length} citations
						</span>
					</div>
					<p className="text-body-sm text-muted-foreground">{finding.detail}</p>
					{Object.keys(finding.metrics).length > 0 && (
						<p className="text-caption-mono-sm text-muted-foreground">
							{Object.entries(finding.metrics)
								.map(([key, value]) => `${key}=${String(value)}`)
								.join(" · ")}
						</p>
					)}
				</li>
			))}
		</ul>
	);
}

function VerificationSummary({
	verification,
}: {
	verification: VerificationReport | null;
}) {
	if (!verification) {
		return (
			<p className="text-body-sm text-muted-foreground">
				No verification report recorded for this run.
			</p>
		);
	}
	return (
		<div className="flex flex-col gap-3">
			<div className="flex flex-wrap items-center gap-2">
				{verification.accepted ? (
					<Badge variant="compliant">Accepted</Badge>
				) : (
					<Badge variant="risk">Rejected</Badge>
				)}
				<span className="text-body-sm text-muted-foreground">
					{verification.checked_claims.length} claims re-derived
				</span>
				{verification.llm_reviewed ? (
					<Badge variant="outline">
						LLM review
						{verification.model_id ? `: ${verification.model_id}` : ""}
					</Badge>
				) : (
					<Badge variant="outline">Deterministic checks only</Badge>
				)}
			</div>
			{verification.challenges.length > 0 && (
				<ul className="flex flex-col gap-2">
					{verification.challenges.map((challenge) => (
						<li
							key={`${challenge.kind}-${challenge.detail}`}
							className="flex flex-col gap-1 rounded-md border border-border p-3"
						>
							<div className="flex flex-wrap items-center gap-2">
								<span className="text-body-sm text-foreground">
									{challenge.kind.replaceAll("_", " ")}
								</span>
								<Badge
									variant={SEVERITY_VARIANT[challenge.severity] ?? "outline"}
								>
									{challenge.severity}
								</Badge>
								<span className="text-caption-mono-sm text-muted-foreground">
									{challenge.source}
								</span>
							</div>
							<p className="text-body-sm text-muted-foreground">
								{challenge.detail}
							</p>
							{(challenge.expected || challenge.observed) && (
								<p className="text-caption-mono-sm text-muted-foreground">
									expected={challenge.expected ?? "—"} · observed=
									{challenge.observed ?? "—"}
								</p>
							)}
						</li>
					))}
				</ul>
			)}
			{verification.notes.length > 0 && (
				<ul className="flex list-disc flex-col gap-1 pl-5">
					{verification.notes.map((note) => (
						<li key={note} className="text-body-sm text-muted-foreground">
							{note}
						</li>
					))}
				</ul>
			)}
		</div>
	);
}

export function AssessmentPanel({
	verdict,
	verification,
	disclosures,
}: {
	verdict: VerdictOut | null;
	verification: VerificationReport | null;
	disclosures: ReadonlyArray<string>;
}) {
	if (!verdict) {
		return (
			<Alert>
				<AlertTriangleIcon aria-hidden="true" />
				<AlertTitle>No assessment released yet</AlertTitle>
				<AlertDescription>
					The deterministic rubric has not published a verdict for this run. If
					it is awaiting review, the pending assessment appears once you open
					the review dialog.
				</AlertDescription>
			</Alert>
		);
	}

	const assessment = verdict.assessment;

	return (
		<div className="flex flex-col gap-6">
			{verdict.pending && (
				<Alert>
					<AlertTriangleIcon aria-hidden="true" />
					<AlertTitle>DDS withheld — human review required</AlertTitle>
					<AlertDescription>
						The ambiguous verdict keeps the DDS in{" "}
						<code>pending_assessment</code>. Record an approve or override
						decision to release it.
					</AlertDescription>
				</Alert>
			)}
			<div className="flex flex-wrap items-center gap-3">
				<VerdictBadge verdict={assessment.verdict} />
				<RiskLevelBadge level={assessment.risk_level} />
				<span className="text-body-sm text-muted-foreground">
					score{" "}
					<span className="tabular-nums text-foreground">
						{formatNumber(assessment.score)}
					</span>
				</span>
				<span className="text-caption-mono-sm text-muted-foreground">
					rubric {assessment.rubric_version}
				</span>
			</div>
			<div className="grid gap-4 lg:grid-cols-2">
				<Card>
					<CardHeader>
						<CardTitle>Findings</CardTitle>
						<CardDescription>
							Deterministic points and citations per signal.
						</CardDescription>
					</CardHeader>
					<CardContent>
						<FindingsList assessment={assessment} />
					</CardContent>
				</Card>
				<Card>
					<CardHeader>
						<CardTitle>Verification</CardTitle>
						<CardDescription>
							Independent re-derivation and citation validation.
						</CardDescription>
					</CardHeader>
					<CardContent>
						<VerificationSummary verification={verification} />
					</CardContent>
				</Card>
			</div>
			<Card>
				<CardHeader>
					<CardTitle className="flex items-center gap-2">
						<CheckCircle2Icon
							aria-hidden="true"
							className="size-4 text-muted-foreground"
						/>
						Design expectations
					</CardTitle>
					<CardDescription>
						Seed labels used to calibrate the 30/12/8 batch design.
					</CardDescription>
				</CardHeader>
				<CardContent className="flex flex-col gap-3">
					<p className="text-body-sm text-muted-foreground">
						Expected archetype{" "}
						<span className="text-foreground">
							{verdict.expected_archetype}
						</span>
						{verdict.expected_signal
							? ` · signal ${verdict.expected_signal}`
							: ""}
						{verdict.expected_ambiguity
							? ` · ambiguity ${verdict.expected_ambiguity}`
							: ""}
					</p>
					<Separator />
					<div className="flex flex-col gap-1">
						<p className="eyebrow-sm text-muted-foreground">Data gaps</p>
						{assessment.data_gaps.length === 0 ? (
							<p className="text-body-sm text-muted-foreground">
								None reported.
							</p>
						) : (
							<ul className="list-disc pl-5">
								{assessment.data_gaps.map((gap) => (
									<li key={gap} className="text-body-sm text-muted-foreground">
										{gap}
									</li>
								))}
							</ul>
						)}
					</div>
					<div className="flex flex-col gap-1">
						<p className="eyebrow-sm text-muted-foreground">Disclosures</p>
						<ul className="list-disc pl-5">
							{[...new Set([...assessment.disclosures, ...disclosures])].map(
								(item) => (
									<li key={item} className="text-body-sm text-muted-foreground">
										{item}
									</li>
								),
							)}
						</ul>
					</div>
					<p className="text-caption-mono-sm text-muted-foreground">
						fingerprint {verdict.fingerprint}
					</p>
				</CardContent>
			</Card>
		</div>
	);
}

import type { ErpMode } from "@terrasentry/api-client";
import { useState } from "react";

import { ErrorState } from "#/components/error-state";
import { Markdown } from "#/components/markdown";
import { VerdictBadge } from "#/components/status-badge";
import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import {
	Dialog,
	DialogClose,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
	DialogTrigger,
} from "#/components/ui/dialog";
import {
	Field,
	FieldContent,
	FieldDescription,
	FieldGroup,
	FieldLabel,
	FieldLegend,
	FieldSet,
	FieldTitle,
} from "#/components/ui/field";
import { Input } from "#/components/ui/input";
import { RadioGroup, RadioGroupItem } from "#/components/ui/radio-group";
import { Spinner } from "#/components/ui/spinner";
import { Textarea } from "#/components/ui/textarea";
import {
	CHOICE_LABEL,
	contradictsRubric,
	type ReviewChoice,
	sapEffect,
} from "#/features/runs/decision";
import { useRunDecision } from "#/features/runs/mutations";

export interface ReviewFinding {
	readonly code: string;
	readonly level: string;
	readonly detail: string;
}

const CHOICES: ReadonlyArray<ReviewChoice> = ["approve", "override"];

/** Findings a reviewer needs first: flags before borderlines, at most three. */
export function topFindings(
	findings: ReadonlyArray<ReviewFinding>,
	limit = 3,
): ReadonlyArray<ReviewFinding> {
	const rank = (level: string) =>
		level === "flag" ? 0 : level === "borderline" ? 1 : 2;
	return [...findings]
		.filter((finding) => finding.level !== "clear")
		.sort((a, b) => rank(a.level) - rank(b.level))
		.slice(0, limit);
}

export function ReviewDialog({
	runId,
	verdict,
	erpMode = "auto",
	brief,
	findings = [],
}: {
	runId: string;
	verdict: string | null;
	erpMode?: ErpMode;
	/** The agents' written summary; context for the reviewer, never the verdict. */
	brief?: string;
	findings?: ReadonlyArray<ReviewFinding>;
}) {
	const [open, setOpen] = useState(false);
	const [choice, setChoice] = useState<ReviewChoice | null>(
		verdict === "high_risk" ? "override" : null,
	);
	const [reviewer, setReviewer] = useState("demo-reviewer");
	const [note, setNote] = useState("");
	const mutation = useRunDecision(runId);

	const noteNeeded = choice !== null && contradictsRubric(verdict, choice);
	const noteMissing = noteNeeded && note.trim() === "";
	const flagged = topFindings(findings);

	const submit = async () => {
		if (choice === null || noteMissing) {
			return;
		}
		try {
			await mutation.mutateAsync({
				decision: choice,
				reviewer: reviewer.trim() || "human",
				note: note.trim(),
			});
			setOpen(false);
			setNote("");
		} catch {
			// ErrorState renders the typed API failure.
		}
	};

	return (
		<Dialog open={open} onOpenChange={setOpen}>
			<DialogTrigger render={<Button />}>Review and decide</DialogTrigger>
			<DialogContent className="sm:max-w-xl">
				<DialogHeader>
					<DialogTitle>Decide on this supplier</DialogTitle>
					<DialogDescription>
						The rubric verdict stays on the record whatever you choose. Nothing
						changes in SAP until you decide.
					</DialogDescription>
				</DialogHeader>
				<form
					className="flex flex-col gap-4 min-w-0"
					onSubmit={(event) => {
						event.preventDefault();
						void submit();
					}}
				>
					<section
						aria-label="Reviewer brief"
						className="flex flex-col gap-2.5 rounded-md border border-border bg-canvas-card/40 p-3 min-w-0"
					>
						<div className="flex items-center gap-2">
							<span className="eyebrow-sm text-muted-foreground">
								Rubric verdict
							</span>
							<VerdictBadge verdict={verdict} />
						</div>
						{flagged.length > 0 && (
							<ul className="flex flex-col gap-1.5 text-body-sm">
								{flagged.map((finding) => (
									<li key={finding.code} className="flex items-start gap-2 min-w-0">
										<Badge
											variant={finding.level === "flag" ? "risk" : "review"}
											className="mt-0.5 shrink-0"
										>
											{finding.level}
										</Badge>
										<span className="text-foreground leading-snug break-words min-w-0">
											{finding.detail}
										</span>
									</li>
								))}
							</ul>
						)}
						{brief && (
							<div className="flex flex-col gap-1 border-t border-border/50 pt-2 text-body-sm min-w-0">
								<span className="text-caption-mono-sm font-medium uppercase text-muted-foreground">
									Agent brief
								</span>
								<div className="max-h-56 overflow-x-hidden overflow-y-auto break-words rounded-md border border-border/50 bg-canvas-soft/60 p-3 text-xs text-muted-foreground [&_h1]:text-xs [&_h1]:font-medium [&_h1]:text-foreground [&_h2]:text-xs [&_h2]:font-medium [&_h2]:text-foreground [&_h2]:border-none [&_h2]:mt-2 [&_h2]:mb-1 [&_h3]:text-xs [&_h3]:font-medium [&_h3]:text-foreground [&_p]:text-xs [&_p]:leading-relaxed [&_p]:mb-1.5 [&_p:last-child]:mb-0 [&_ul]:my-1 [&_li]:text-xs">
									<Markdown content={brief} />
								</div>
							</div>
						)}
					</section>
					<FieldSet>
						<FieldLegend variant="label">Your decision</FieldLegend>
						<RadioGroup
							value={choice ?? ""}
							onValueChange={(value) => setChoice(value as ReviewChoice)}
							className="grid gap-3"
						>
							{CHOICES.map((option) => (
								<FieldLabel
									key={option}
									htmlFor={`decision-${option}`}
									className="cursor-pointer rounded-md border border-border/70 bg-canvas-card/30 transition-colors hover:border-border hover:bg-canvas-card/60"
								>
									<Field orientation="horizontal">
										<RadioGroupItem value={option} id={`decision-${option}`} />
										<FieldContent>
											<FieldTitle>{CHOICE_LABEL[option]}</FieldTitle>
											<FieldDescription>
												{sapEffect(option, erpMode)}
											</FieldDescription>
										</FieldContent>
									</Field>
								</FieldLabel>
							))}
						</RadioGroup>
					</FieldSet>
					<FieldGroup>
						<Field>
							<FieldLabel htmlFor="reviewer">Reviewer</FieldLabel>
							<Input
								id="reviewer"
								name="reviewer"
								autoComplete="off"
								value={reviewer}
								onChange={(event) => setReviewer(event.target.value)}
							/>
						</Field>
						<Field data-invalid={noteMissing || undefined}>
							<FieldLabel htmlFor="note">
								Note{noteNeeded ? " (required)" : ""}
							</FieldLabel>
							<Textarea
								id="note"
								name="note"
								rows={3}
								aria-invalid={noteMissing || undefined}
								placeholder="Checked the permit gap with the operator…"
								value={note}
								onChange={(event) => setNote(event.target.value)}
							/>
							{noteNeeded && (
								<FieldDescription>
									Approving a high-risk supplier overrides the rubric. Say why;
									the note is kept with the decision.
								</FieldDescription>
							)}
						</Field>
					</FieldGroup>
					{mutation.error && <ErrorState error={mutation.error} />}
					<DialogFooter>
						<DialogClose render={<Button variant="outline" type="button" />}>
							Cancel
						</DialogClose>
						<Button
							type="submit"
							disabled={mutation.isPending || choice === null || noteMissing}
						>
							{mutation.isPending && (
								<Spinner
									aria-label="Recording decision"
									data-icon="inline-start"
								/>
							)}
							{choice === null ? "Choose a decision" : CHOICE_LABEL[choice]}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}

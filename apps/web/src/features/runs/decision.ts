import type { ErpMode } from "@terrasentry/api-client";

/** The API keeps `approve | override`; the UI speaks about the supplier. */
export type ReviewChoice = "approve" | "override";

export const CHOICE_LABEL: Record<ReviewChoice, string> = {
	approve: "Approve supplier",
	override: "Block supplier",
};

const SAP_EFFECT: Record<ReviewChoice, string> = {
	approve: "SAP: vendor set to approved, purchasing block cleared",
	override: "SAP: vendor blocked, purchasing block set",
};

/** What a decision does in SAP, given how the run was started. */
export function sapEffect(
	choice: ReviewChoice,
	erpMode: ErpMode = "auto",
): string {
	if (erpMode === "off") {
		return "SAP is not touched for this run; the decision is recorded only";
	}
	if (erpMode === "confirm") {
		return `${SAP_EFFECT[choice]}, once you confirm it on the run page`;
	}
	return SAP_EFFECT[choice];
}

/** Approving a high-risk supplier overrides the rubric, so it needs a reason. */
export function contradictsRubric(
	verdict: string | null | undefined,
	choice: ReviewChoice,
): boolean {
	return verdict === "high_risk" && choice === "approve";
}

export function noteRequired(
	verdicts: ReadonlyArray<string | null | undefined>,
	choice: ReviewChoice,
): boolean {
	return verdicts.some((verdict) => contradictsRubric(verdict, choice));
}

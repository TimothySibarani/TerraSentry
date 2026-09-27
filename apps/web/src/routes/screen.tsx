import type { ModelMode } from "@terrasentry/api-client";
import { ApiClientError } from "@terrasentry/api-client";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { ArrowLeftIcon, ArrowRightIcon, RadarIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { ErrorState } from "#/components/error-state";
import { PageHeader } from "#/components/page-header";
import { Stepper, type StepStatus } from "#/components/stepper";
import { Button } from "#/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardFooter,
	CardHeader,
	CardTitle,
} from "#/components/ui/card";
import { Spinner } from "#/components/ui/spinner";
import {
	ConsignmentStep,
	LegalityStep,
	SupplierStep,
} from "#/features/intake/detail-steps";
import { fieldId } from "#/features/intake/fields";
import {
	type FieldErrors,
	type IntakeForm,
	initialForm,
	issuesToErrors,
	STEP_IDS,
	STEPS,
	type StepId,
	stepOfField,
	validateStep,
} from "#/features/intake/form";
import { PlotStep } from "#/features/intake/plot-step";
import { useScreenPlot } from "#/features/intake/queries";
import { ReviewStep } from "#/features/intake/review-step";
import { useDefaultModel } from "#/features/runs/model-select";

export const Route = createFileRoute("/screen")({
	validateSearch: (search: Record<string, unknown>): { step?: StepId } => ({
		step: STEP_IDS.includes(search.step as StepId)
			? (search.step as StepId)
			: undefined,
	}),
	head: () => ({ meta: [{ title: "Screen a plot — TerraSentry" }] }),
	component: ScreenPlotPage,
});

function ScreenPlotPage() {
	const { step: requested = "plot" } = Route.useSearch();
	const navigate = useNavigate({ from: Route.fullPath });
	const [form, setForm] = useState<IntakeForm>(initialForm);
	const [errors, setErrors] = useState<FieldErrors>({});
	const [serverStep, setServerStep] = useState<StepId | null>(null);
	const defaultModel = useDefaultModel();
	const [modelChoice, setModelChoice] = useState<ModelMode | null>(null);
	const model = modelChoice ?? defaultModel;
	const screen = useScreenPlot();
	const headingRef = useRef<HTMLHeadingElement>(null);

	// A step is reachable only when every earlier step validates, so a deep
	// link to ?step=review on an empty form lands on the first gap instead.
	const firstInvalid = useMemo(
		() =>
			STEP_IDS.find(
				(id) =>
					id !== "review" && Object.keys(validateStep(id, form)).length > 0,
			) ?? null,
		[form],
	);
	const reachable = (id: StepId) => {
		const limit = firstInvalid
			? STEP_IDS.indexOf(firstInvalid)
			: STEP_IDS.length;
		return STEP_IDS.indexOf(id) <= limit;
	};
	const step: StepId = reachable(requested)
		? requested
		: (firstInvalid ?? "plot");
	const index = STEP_IDS.indexOf(step);

	const goTo = (next: StepId) => {
		void navigate({ search: { step: next }, replace: false });
	};

	// Move focus to the step heading on navigation (screen readers + keyboard).
	// biome-ignore lint/correctness/useExhaustiveDependencies: step change is the trigger
	useEffect(() => {
		headingRef.current?.focus();
	}, [step]);

	const update = (patch: Partial<IntakeForm>) => {
		setForm((current) => ({ ...current, ...patch }));
		setErrors({});
		setServerStep(null);
	};

	const next = () => {
		const stepErrors = validateStep(step, form);
		setErrors(stepErrors);
		const first = Object.keys(stepErrors)[0];
		if (first) {
			document.getElementById(fieldId(first))?.focus();
			return;
		}
		const following = STEP_IDS[index + 1];
		if (following) {
			goTo(following);
		}
	};

	const submit = () => {
		setServerStep(null);
		screen.mutate(
			{ form, model },
			{
				onSuccess: ({ run }) =>
					void navigate({
						to: "/runs/$runId",
						params: { runId: run.run_id },
						search: { tab: "trace" },
					}),
				onError: (error) => {
					if (error instanceof ApiClientError && error.issues?.length) {
						const mapped = issuesToErrors(error.issues);
						const first = Object.keys(mapped)[0] ?? "";
						const target = stepOfField(first);
						setErrors(mapped);
						setServerStep(target);
						goTo(target);
					}
				},
			},
		);
	};

	const stepStatus = (id: StepId, position: number): StepStatus => {
		if (serverStep === id) {
			return "error";
		}
		if (id === step) {
			return "current";
		}
		const valid =
			id === "review" || Object.keys(validateStep(id, form)).length === 0;
		return position < index && valid ? "complete" : "upcoming";
	};

	const meta = STEPS[index] ?? STEPS[0];
	const unmappedServerError =
		screen.error &&
		!(screen.error instanceof ApiClientError && screen.error.issues?.length)
			? screen.error
			: null;

	return (
		<div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
			<PageHeader
				eyebrow="New screening"
				title="Screen a plot"
				description="Map a supplier's plot and declare its legality and consignment. Agents check it against real Hansen tree-cover loss and NASA FIRMS fire data, a deterministic rubric scores it, and an independent verifier signs off before the EUDR statement is released."
			/>
			<div className="grid gap-6 lg:grid-cols-[15rem_minmax(0,1fr)]">
				<Stepper
					label="Screening steps"
					className="lg:sticky lg:top-20 lg:self-start"
					onSelect={(id) => reachable(id as StepId) && goTo(id as StepId)}
					steps={STEPS.map((item, position) => ({
						id: item.id,
						title: item.title,
						description: item.description,
						status: stepStatus(item.id, position),
						disabled: !reachable(item.id),
					}))}
				/>
				<Card>
					<CardHeader className="border-b border-border">
						<p className="eyebrow-sm text-muted-foreground">
							Step {index + 1} of {STEPS.length}
						</p>
						<CardTitle>
							<h2
								ref={headingRef}
								tabIndex={-1}
								className="text-display-xs text-foreground outline-none"
							>
								{meta.title}
							</h2>
						</CardTitle>
						<CardDescription>{meta.description}</CardDescription>
					</CardHeader>
					<CardContent className="flex flex-col gap-4">
						{step === "plot" && (
							<PlotStep form={form} update={update} errors={errors} />
						)}
						{step === "supplier" && (
							<SupplierStep form={form} update={update} errors={errors} />
						)}
						{step === "legality" && (
							<LegalityStep form={form} update={update} errors={errors} />
						)}
						{step === "consignment" && (
							<ConsignmentStep form={form} update={update} errors={errors} />
						)}
						{step === "review" && (
							<ReviewStep
								form={form}
								model={model}
								onModelChange={setModelChoice}
								onEdit={goTo}
							/>
						)}
						{unmappedServerError && <ErrorState error={unmappedServerError} />}
					</CardContent>
					<CardFooter className="justify-between gap-2 border-t border-border">
						<Button
							variant="ghost"
							disabled={index === 0 || screen.isPending}
							onClick={() => {
								const previous = STEP_IDS[index - 1];
								if (previous) {
									goTo(previous);
								}
							}}
						>
							<ArrowLeftIcon data-icon="inline-start" aria-hidden="true" />
							Back
						</Button>
						{step === "review" ? (
							<Button disabled={screen.isPending} onClick={submit}>
								{screen.isPending ? (
									<Spinner
										aria-label="Starting screening"
										data-icon="inline-start"
									/>
								) : (
									<RadarIcon data-icon="inline-start" aria-hidden="true" />
								)}
								{screen.isPending ? "Starting agents…" : "Screen this plot"}
							</Button>
						) : (
							<Button onClick={next}>
								Continue
								<ArrowRightIcon data-icon="inline-end" aria-hidden="true" />
							</Button>
						)}
					</CardFooter>
				</Card>
			</div>
		</div>
	);
}

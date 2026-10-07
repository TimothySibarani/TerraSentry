import { useNavigate } from "@tanstack/react-router";
import type { BatchMode, ModelMode } from "@terrasentry/api-client";
import { LayersIcon, PlayIcon } from "lucide-react";
import { useState } from "react";

import { ErrorState } from "#/components/error-state";
import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
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
import { RadioGroup, RadioGroupItem } from "#/components/ui/radio-group";
import {
	Select,
	SelectContent,
	SelectGroup,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "#/components/ui/select";
import { Spinner } from "#/components/ui/spinner";
import { ModelSelect, useDefaultModel } from "#/features/runs/model-select";
import { useCreateBatch, useCreateRun } from "#/features/runs/mutations";
import { scenariosFor } from "#/features/runs/scenarios";

const BATCH_MODES: ReadonlyArray<{
	value: BatchMode;
	title: string;
	description: string;
}> = [
	{
		value: "screening",
		title: "Fast screening",
		description: "Rubric + deterministic verifier, no LLM",
	},
	{
		value: "agent",
		title: "Agent investigation",
		description:
			"Full agent graph per record: screening, deep dives, verifier. Slower, a few records at a time",
	},
];

const CACHE_ITEMS = {
	cache: "Use cached sources",
	refresh: "Refresh from sources",
} as const;

export function RunLauncher({
	showBatch = true,
	showScenarios = true,
}: {
	showBatch?: boolean;
	showScenarios?: boolean;
}) {
	const navigate = useNavigate();
	const createRun = useCreateRun();
	const createBatch = useCreateBatch();
	const defaultModel = useDefaultModel();
	const [model, setModel] = useState<ModelMode | null>(null);
	const selectedModel = model ?? defaultModel;
	const [cacheMode, setCacheMode] = useState<"cache" | "refresh">("cache");
	const [batchMode, setBatchMode] = useState<BatchMode>("screening");

	const refresh = cacheMode === "refresh";
	const scenarios = scenariosFor(selectedModel);
	const faultScenarios = scenarios.filter(
		(scenario) => scenario.faultInjection,
	);

	const startScenario = (scenario: string) => {
		createRun.mutate(
			{ scenario, model: selectedModel, refresh },
			{
				onSuccess: (run) =>
					void navigate({
						to: "/runs/$runId",
						params: { runId: run.run_id },
					}),
			},
		);
	};

	const startBatch = () => {
		createBatch.mutate(
			batchMode === "agent"
				? { size: 50, refresh, mode: "agent", model: selectedModel }
				: { size: 50, refresh, mode: "screening" },
			{
				onSuccess: (batch) =>
					void navigate({
						to: "/batch/$batchId",
						params: { batchId: batch.run_id },
					}),
			},
		);
	};

	// A batch-only launcher has no scenarios that need a model, so screening disables it.
	const modelDisabled =
		showBatch && !showScenarios && batchMode === "screening";
	const pending = createRun.isPending || createBatch.isPending;
	const error = createRun.error ?? createBatch.error;

	return (
		<div className="flex flex-col gap-4">
			<FieldGroup className="flex-row flex-wrap items-end gap-3">
				<ModelSelect
					id="run-model"
					className="w-52"
					value={selectedModel}
					onChange={setModel}
					disabled={modelDisabled}
					disabledHint="Screening uses no model."
				/>
				<Field className="w-52">
					<FieldLabel htmlFor="run-cache">Source data</FieldLabel>
					<Select
						items={CACHE_ITEMS}
						value={cacheMode}
						onValueChange={(value) =>
							setCacheMode(value as "cache" | "refresh")
						}
					>
						<SelectTrigger id="run-cache" className="w-full">
							<SelectValue />
						</SelectTrigger>
						<SelectContent>
							<SelectGroup>
								<SelectItem value="cache">Use cached sources</SelectItem>
								<SelectItem value="refresh">Refresh from sources</SelectItem>
							</SelectGroup>
						</SelectContent>
					</Select>
				</Field>
			</FieldGroup>

			{showBatch && (
				<FieldSet>
					<FieldLegend variant="label">Batch mode</FieldLegend>
					<RadioGroup
						value={batchMode}
						onValueChange={(value) => setBatchMode(value as BatchMode)}
						className="grid gap-3 md:grid-cols-2"
					>
						{BATCH_MODES.map((option) => (
							<FieldLabel
								key={option.value}
								htmlFor={`batch-mode-${option.value}`}
							>
								<Field orientation="horizontal">
									<RadioGroupItem
										value={option.value}
										id={`batch-mode-${option.value}`}
									/>
									<FieldContent>
										<FieldTitle>{option.title}</FieldTitle>
										<FieldDescription>{option.description}</FieldDescription>
									</FieldContent>
								</Field>
							</FieldLabel>
						))}
					</RadioGroup>
				</FieldSet>
			)}

			<div className="flex flex-wrap items-center gap-2">
				{showScenarios &&
					scenarios.map((scenario) => (
						<Button
							key={scenario.id}
							variant={scenario.id === "high_risk_live" ? "default" : "outline"}
							disabled={pending}
							onClick={() => startScenario(scenario.id)}
						>
							{createRun.isPending ? (
								<Spinner aria-label="Starting run" data-icon="inline-start" />
							) : (
								<PlayIcon data-icon="inline-start" aria-hidden="true" />
							)}
							{scenario.label}
							{scenario.faultInjection && (
								<Badge variant="review">Fault injection</Badge>
							)}
						</Button>
					))}
				{showBatch && (
					<Button variant="outline" disabled={pending} onClick={startBatch}>
						{createBatch.isPending ? (
							<Spinner aria-label="Starting batch" data-icon="inline-start" />
						) : (
							<LayersIcon data-icon="inline-start" aria-hidden="true" />
						)}
						{batchMode === "agent"
							? "Run 50-record agent batch"
							: "Run 50-record screening"}
					</Button>
				)}
			</div>

			{showScenarios &&
				faultScenarios.map((scenario) => (
					<p key={scenario.id} className="text-body-sm text-muted-foreground">
						<span className="text-foreground">Fault injection:</span>{" "}
						{scenario.description}
					</p>
				))}

			{error && <ErrorState error={error} />}
		</div>
	);
}

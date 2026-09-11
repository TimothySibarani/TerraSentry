import type { ModelMode } from "@terrasentry/api-client";
import { useNavigate } from "@tanstack/react-router";
import { LayersIcon, PlayIcon } from "lucide-react";
import { useState } from "react";

import { ErrorState } from "#/components/error-state";
import { Button } from "#/components/ui/button";
import { Field, FieldGroup, FieldLabel } from "#/components/ui/field";
import {
	Select,
	SelectContent,
	SelectGroup,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "#/components/ui/select";
import { Spinner } from "#/components/ui/spinner";
import { useCreateBatch, useCreateRun } from "#/features/runs/mutations";
import { DEMO_SCENARIOS } from "#/features/runs/scenarios";

const MODEL_ITEMS = {
	scripted: "Scripted (offline)",
	bedrock: "Bedrock (live)",
} as const;

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
	const [model, setModel] = useState<ModelMode>("scripted");
	const [cacheMode, setCacheMode] = useState<"cache" | "refresh">("cache");

	const refresh = cacheMode === "refresh";

	const startScenario = (scenario: string) => {
		createRun.mutate(
			{ scenario, model, refresh },
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
			{ size: 50, refresh },
			{
				onSuccess: (batch) =>
					void navigate({
						to: "/batch/$batchId",
						params: { batchId: batch.run_id },
					}),
			},
		);
	};

	const pending = createRun.isPending || createBatch.isPending;
	const error = createRun.error ?? createBatch.error;

	return (
		<div className="flex flex-col gap-4">
			<FieldGroup className="flex-row flex-wrap items-end gap-3">
				<Field className="w-44">
					<FieldLabel htmlFor="run-model">Model</FieldLabel>
					<Select
						items={MODEL_ITEMS}
						value={model}
						onValueChange={(value) => setModel(value as ModelMode)}
					>
						<SelectTrigger id="run-model" className="w-full">
							<SelectValue />
						</SelectTrigger>
						<SelectContent>
							<SelectGroup>
								<SelectItem value="scripted">Scripted (offline)</SelectItem>
								<SelectItem value="bedrock">Bedrock (live)</SelectItem>
							</SelectGroup>
						</SelectContent>
					</Select>
				</Field>
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

			<div className="flex flex-wrap items-center gap-2">
				{showScenarios &&
					DEMO_SCENARIOS.map((scenario) => (
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
						</Button>
					))}
				{showBatch && (
					<Button variant="outline" disabled={pending} onClick={startBatch}>
						{createBatch.isPending ? (
							<Spinner aria-label="Starting batch" data-icon="inline-start" />
						) : (
							<LayersIcon data-icon="inline-start" aria-hidden="true" />
						)}
						Run 50-record batch
					</Button>
				)}
			</div>

			{error && <ErrorState error={error} />}
		</div>
	);
}

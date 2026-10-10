import { useQuery } from "@tanstack/react-query";
import type { ModelMode } from "@terrasentry/api-client";
import { useEffect } from "react";

import { Field, FieldDescription, FieldLabel } from "#/components/ui/field";
import {
	Select,
	SelectContent,
	SelectGroup,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "#/components/ui/select";
import { healthQuery } from "#/features/health/queries";

const MODEL_ITEMS = {
	scripted: "Scripted (offline)",
	bedrock: "Bedrock (live)",
	sap: "SAP AI Core (live)",
} as const;

/**
 * Agent model picker. Each live option is disabled until `/health` reports its
 * credentials and both role model ids, so a run can never be started against
 * missing config.
 */
export function ModelSelect({
	id,
	value,
	onChange,
	className,
	showHint = false,
	disabled = false,
	disabledHint,
}: {
	id: string;
	value: ModelMode;
	onChange: (value: ModelMode) => void;
	className?: string;
	showHint?: boolean;
	disabled?: boolean;
	/** Shown instead of the hint when the picker is disabled, to say why. */
	disabledHint?: string;
}) {
	const health = useQuery(healthQuery());
	const bedrockReady = health.data?.bedrockConfigured ?? false;
	const sapReady = health.data?.aicoreConfigured ?? false;
	const selectedReady =
		value === "scripted" || (value === "bedrock" ? bedrockReady : sapReady);

	// Fall back to scripted if live models disappear (config change, API restart).
	useEffect(() => {
		if (health.isSuccess && !selectedReady) {
			onChange("scripted");
		}
	}, [selectedReady, health.isSuccess, onChange]);

	return (
		<Field className={className} data-disabled={disabled || undefined}>
			<FieldLabel htmlFor={id}>Agent model</FieldLabel>
			<Select
				items={MODEL_ITEMS}
				disabled={disabled}
				value={value}
				onValueChange={(next) => onChange(next as ModelMode)}
			>
				<SelectTrigger id={id} className="w-full">
					<SelectValue />
				</SelectTrigger>
				<SelectContent>
					<SelectGroup>
						<SelectItem value="scripted">Scripted (offline)</SelectItem>
						<SelectItem value="bedrock" disabled={!bedrockReady}>
							Bedrock (live){bedrockReady ? "" : " — not configured"}
						</SelectItem>
						<SelectItem value="sap" disabled={!sapReady}>
							SAP AI Core (live){sapReady ? "" : " — not configured"}
						</SelectItem>
					</SelectGroup>
				</SelectContent>
			</Select>
			{disabled && disabledHint ? (
				<FieldDescription>{disabledHint}</FieldDescription>
			) : null}
			{showHint && !disabled && (
				<FieldDescription>
					{hintFor(value, { bedrockReady, sapReady })}
				</FieldDescription>
			)}
		</Field>
	);
}

function hintFor(
	value: ModelMode,
	ready: { bedrockReady: boolean; sapReady: boolean },
): string {
	const live =
		"runs the supervisor, specialists, and verifier on live models. Scripted replays the same graph with no model calls.";
	if (value === "sap" && ready.sapReady) return `SAP AI Core ${live}`;
	if (value === "bedrock" && ready.bedrockReady) return `Bedrock ${live}`;
	return "Set BEDROCK_MODEL_ORCHESTRATOR and BEDROCK_MODEL_EXTRACTION (Bedrock) or AICORE_SERVICE_KEY, AICORE_MODEL_ORCHESTRATOR and AICORE_MODEL_EXTRACTION (SAP AI Core) to enable live models. Scripted still uses real GFW and FIRMS data.";
}

/** The model a new run should start with: live when available and preferred. */
export function useDefaultModel(): ModelMode {
	const health = useQuery(healthQuery());
	if (
		health.data?.defaultModel === "bedrock" &&
		health.data.bedrockConfigured
	) {
		return "bedrock";
	}
	if (health.data?.defaultModel === "sap" && health.data.aicoreConfigured) {
		return "sap";
	}
	return "scripted";
}

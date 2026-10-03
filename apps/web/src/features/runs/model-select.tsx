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
} as const;

/**
 * Agent model picker. "Bedrock (live)" is disabled until `/health` reports
 * both role model ids, so a run can never be started against missing config.
 */
export function ModelSelect({
	id,
	value,
	onChange,
	className,
	showHint = false,
}: {
	id: string;
	value: ModelMode;
	onChange: (value: ModelMode) => void;
	className?: string;
	showHint?: boolean;
}) {
	const health = useQuery(healthQuery());
	const bedrockReady = health.data?.bedrockConfigured ?? false;

	// Fall back to scripted if live models disappear (config change, API restart).
	useEffect(() => {
		if (value === "bedrock" && health.isSuccess && !bedrockReady) {
			onChange("scripted");
		}
	}, [value, bedrockReady, health.isSuccess, onChange]);

	return (
		<Field className={className}>
			<FieldLabel htmlFor={id}>Agent model</FieldLabel>
			<Select
				items={MODEL_ITEMS}
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
					</SelectGroup>
				</SelectContent>
			</Select>
			{showHint && (
				<FieldDescription>
					{bedrockReady
						? "Bedrock runs the supervisor, specialists, and verifier on live models. Scripted replays the same graph with no model calls."
						: "Set BEDROCK_MODEL_ORCHESTRATOR and BEDROCK_MODEL_EXTRACTION to enable live models. Scripted still uses real GFW and FIRMS data."}
				</FieldDescription>
			)}
		</Field>
	);
}

/** The model a new run should start with: live when available and preferred. */
export function useDefaultModel(): ModelMode {
	const health = useQuery(healthQuery());
	return health.data?.bedrockConfigured &&
		health.data.defaultModel === "bedrock"
		? "bedrock"
		: "scripted";
}

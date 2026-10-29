import type { ScenarioOut } from "@terrasentry/api-client";
import { EyeIcon, PlayIcon } from "lucide-react";

import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
	DialogTrigger,
} from "#/components/ui/dialog";
import { Spinner } from "#/components/ui/spinner";
import { expectedLabel, RunInputPanel } from "./run-input";

/** One demo scenario: what it submits and what it is built to show, with its Run button. */
export function ScenarioCard({
	scenario,
	pending,
	starting,
	onRun,
}: {
	scenario: ScenarioOut;
	pending: boolean;
	starting: boolean;
	onRun: () => void;
}) {
	const { polygon, legality } = scenario.record;
	const expected = expectedLabel(scenario.record);
	return (
		<article
			aria-label={scenario.label}
			className="flex flex-col gap-2 rounded-lg border border-border bg-canvas-soft/40 p-3"
		>
			<header className="flex flex-wrap items-center gap-2">
				<h4 className="text-body-sm font-medium">{scenario.label}</h4>
				{scenario.fault_injection && (
					<Badge variant="review">Fault injection</Badge>
				)}
				{expected && (
					<Badge variant="outline" className="ml-auto">
						Expected: {expected}
					</Badge>
				)}
			</header>
			<p className="line-clamp-2 text-body-sm text-muted-foreground">
				{scenario.description}
			</p>
			<p className="font-mono text-xs text-muted-foreground">
				{[
					polygon.id,
					polygon.region,
					`${polygon.area_ha.toLocaleString("en-GB", { maximumFractionDigits: 0 })} ha`,
					legality.legal_name,
					`permit ${legality.permit_status}`,
				].join(" · ")}
			</p>
			<div className="flex flex-wrap gap-2">
				<Button
					size="sm"
					variant={scenario.id === "high_risk_live" ? "default" : "outline"}
					disabled={pending}
					onClick={onRun}
					aria-label={`Run ${scenario.label}`}
				>
					{starting ? (
						<Spinner aria-label="Starting run" data-icon="inline-start" />
					) : (
						<PlayIcon data-icon="inline-start" aria-hidden="true" />
					)}
					Run
				</Button>
				<Dialog>
					<DialogTrigger render={<Button size="sm" variant="ghost" />}>
						<EyeIcon data-icon="inline-start" aria-hidden="true" />
						View input
					</DialogTrigger>
					<DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-5xl">
						<DialogHeader>
							<DialogTitle>{scenario.label}: input</DialogTitle>
							<DialogDescription>{scenario.description}</DialogDescription>
						</DialogHeader>
						<RunInputPanel record={scenario.record} />
					</DialogContent>
				</Dialog>
			</div>
		</article>
	);
}

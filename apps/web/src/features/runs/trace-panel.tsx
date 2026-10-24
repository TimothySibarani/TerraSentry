import type { TraceStep } from "@terrasentry/api-client";
import {
	ActivityIcon,
	BotIcon,
	FileOutputIcon,
	FileTextIcon,
	LandmarkIcon,
	RouteIcon,
	ShieldCheckIcon,
	UserCheckIcon,
	WrenchIcon,
} from "lucide-react";

import { ErrorState } from "#/components/error-state";
import { Badge } from "#/components/ui/badge";
import {
	Empty,
	EmptyDescription,
	EmptyHeader,
	EmptyMedia,
	EmptyTitle,
} from "#/components/ui/empty";
import { Skeleton } from "#/components/ui/skeleton";
import { Spinner } from "#/components/ui/spinner";
import type { RunStreamStatus } from "#/features/runs/use-run-stream";
import { formatDateTime } from "#/lib/format";
import { cn } from "#/lib/utils";

const KIND_ICON: Record<string, typeof ActivityIcon> = {
	run: ActivityIcon,
	agent: BotIcon,
	retask: RouteIcon,
	report: FileTextIcon,
	tool: WrenchIcon,
	verifier: ShieldCheckIcon,
	writer: FileOutputIcon,
	review: UserCheckIcon,
	state: ActivityIcon,
	sap: LandmarkIcon,
};

export function TracePanel({
	steps,
	status,
	error,
	onReconnect,
}: {
	steps: ReadonlyArray<TraceStep>;
	status: RunStreamStatus;
	error?: unknown;
	onReconnect?: () => void;
}) {
	if (status === "error" && error) {
		return <ErrorState error={error} onRetry={onReconnect} />;
	}

	if (status === "connecting" && steps.length === 0) {
		return (
			<div className="flex flex-col gap-3">
				<Skeleton className="h-12" />
				<Skeleton className="h-12" />
				<Skeleton className="h-12" />
			</div>
		);
	}

	if (steps.length === 0) {
		return (
			<Empty>
				<EmptyHeader>
					<EmptyMedia variant="icon">
						<Spinner aria-label="Waiting for steps" />
					</EmptyMedia>
					<EmptyTitle>Waiting for the first step…</EmptyTitle>
					<EmptyDescription>
						The run is queued. Supervisor and specialist steps appear here as
						soon as they are persisted.
					</EmptyDescription>
				</EmptyHeader>
			</Empty>
		);
	}

	const retasks = steps.filter((step) => step.kind === "retask");

	return (
		<div className="flex flex-col gap-3">
			<div className="flex flex-wrap items-center gap-2">
				{status === "live" ? (
					<Badge variant="compliant">Live trace</Badge>
				) : status === "closed" ? (
					<Badge variant="outline">Recorded trace</Badge>
				) : (
					<Badge variant="secondary">Reconnecting…</Badge>
				)}
				<span className="text-caption-mono-sm text-muted-foreground">
					{steps.length} steps
				</span>
				{retasks.length > 0 && (
					<Badge variant="review">
						{retasks.length} re-task{retasks.length === 1 ? "" : "s"}:{" "}
						{retasks.map((step) => step.name).join(", ")}
					</Badge>
				)}
			</div>
			<ol
				aria-live="polite"
				aria-label="Agent run steps"
				className="flex flex-col gap-0"
			>
				{steps.map((step, index) => {
					const Icon = KIND_ICON[step.kind] ?? ActivityIcon;
					const payloadKeys = Object.keys(step.payload ?? {});
					const isRetask = step.kind === "retask";
					return (
						<li
							key={step.step_id}
							data-kind={step.kind}
							className={cn(
								"relative flex gap-3 border-l pb-5 pl-4 last:pb-0",
								isRetask
									? "border-status-review bg-status-review/10 py-2 pr-2"
									: "border-border",
							)}
						>
							<span
								aria-hidden="true"
								className={cn(
									"absolute -left-[5px] top-0.5 size-2.5 rounded-full ring-2 ring-background",
									isRetask ? "bg-status-review" : "bg-muted",
								)}
							/>
							<div className="flex min-w-0 flex-1 flex-col gap-1">
								<div className="flex flex-wrap items-center gap-2">
									<Icon
										aria-hidden="true"
										className="size-3.5 text-muted-foreground"
									/>
									<span className="text-body-sm text-foreground">
										{step.name}
									</span>
									{isRetask ? (
										<Badge variant="review">re-task</Badge>
									) : (
										<Badge variant="outline">{step.kind}</Badge>
									)}
									<span className="text-caption-mono-sm text-muted-foreground">
										#{String(index + 1).padStart(2, "0")}
									</span>
									<span className="ml-auto text-caption-mono-sm text-muted-foreground">
										{formatDateTime(step.at)}
									</span>
								</div>
								{step.detail && (
									<p className="text-body-sm text-muted-foreground">
										{isRetask ? (
											<>
												<span className="sr-only">
													Re-task of {step.name}.{" "}
												</span>
												<span className="text-foreground">Reason: </span>
											</>
										) : null}
										{step.detail}
									</p>
								)}
								{step.kind === "report" &&
									typeof step.payload?.report === "string" && (
										<details className="text-body-sm text-muted-foreground">
											<summary className="cursor-pointer select-none text-caption-mono-sm hover:text-foreground">
												Read the {step.name.replaceAll("_", " ")}'s report
											</summary>
											<p className="mt-1 whitespace-pre-wrap rounded-md bg-canvas-soft p-2">
												{step.payload.report}
											</p>
										</details>
									)}
								{step.kind !== "report" && payloadKeys.length > 0 && (
									<details className="text-caption-mono-sm text-muted-foreground">
										<summary className="cursor-pointer select-none hover:text-foreground">
											Payload ({payloadKeys.length} fields)
										</summary>
										<pre className="mt-1 overflow-x-auto rounded-md bg-canvas-soft p-2 text-[11px] leading-relaxed">
											{JSON.stringify(step.payload, null, 2)}
										</pre>
									</details>
								)}
							</div>
						</li>
					);
				})}
			</ol>
		</div>
	);
}

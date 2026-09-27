import { CheckIcon, CircleAlertIcon } from "lucide-react";

import { cn } from "#/lib/utils";

export type StepStatus = "complete" | "current" | "upcoming" | "error";

export interface StepperStep {
	id: string;
	title: string;
	description?: string;
	status: StepStatus;
	/** Upcoming steps stay locked until their predecessors validate. */
	disabled?: boolean;
}

/**
 * Vertical stepper (pattern from Origin UI's stepper on 21st.dev, rebuilt on
 * the project tokens). Each step is a button, so it is keyboard reachable,
 * and the current one carries `aria-current="step"`.
 */
export function Stepper({
	steps,
	onSelect,
	className,
	label = "Steps",
}: {
	steps: ReadonlyArray<StepperStep>;
	onSelect: (id: string) => void;
	className?: string;
	label?: string;
}) {
	return (
		<nav aria-label={label} className={className}>
			<ol className="flex flex-col">
				{steps.map((step, index) => {
					const last = index === steps.length - 1;
					return (
						<li key={step.id} className="relative flex">
							{!last && (
								<span
									aria-hidden="true"
									className={cn(
										"absolute top-8 bottom-1 left-3.5 w-px -translate-x-1/2",
										step.status === "complete"
											? "bg-foreground/60"
											: "bg-border",
									)}
								/>
							)}
							<button
								type="button"
								disabled={step.disabled}
								aria-current={step.status === "current" ? "step" : undefined}
								onClick={() => onSelect(step.id)}
								className={cn(
									"group flex w-full items-start gap-3 rounded-md pb-6 text-left outline-none last:pb-0 focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed",
									last && "pb-0",
								)}
							>
								<span
									className={cn(
										"relative z-10 flex size-7 shrink-0 items-center justify-center rounded-full border text-caption-mono-sm tabular-nums transition-colors",
										step.status === "complete" &&
											"border-foreground bg-foreground text-background",
										step.status === "current" &&
											"border-foreground bg-background text-foreground ring-4 ring-foreground/10",
										step.status === "upcoming" &&
											"border-border bg-background text-muted-foreground",
										step.status === "error" &&
											"border-status-risk bg-status-risk/10 text-status-risk",
									)}
								>
									{step.status === "complete" ? (
										<CheckIcon aria-hidden="true" className="size-3.5" />
									) : step.status === "error" ? (
										<CircleAlertIcon aria-hidden="true" className="size-3.5" />
									) : (
										index + 1
									)}
									<span className="sr-only">
										{step.status === "complete"
											? "Completed: "
											: step.status === "error"
												? "Needs attention: "
												: ""}
									</span>
								</span>
								<span className="flex min-w-0 flex-col gap-0.5 pt-0.5">
									<span
										className={cn(
											"text-body-sm",
											step.status === "upcoming"
												? "text-muted-foreground"
												: "text-foreground",
											!step.disabled && "group-hover:text-foreground",
										)}
									>
										{step.title}
									</span>
									{step.description && (
										<span className="text-xs text-muted-foreground">
											{step.description}
										</span>
									)}
								</span>
							</button>
						</li>
					);
				})}
			</ol>
		</nav>
	);
}

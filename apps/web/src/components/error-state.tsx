import { useQueryErrorResetBoundary } from "@tanstack/react-query";
import { useRouter } from "@tanstack/react-router";
import { RotateCcwIcon } from "lucide-react";

import {
	Alert,
	AlertAction,
	AlertDescription,
	AlertTitle,
} from "#/components/ui/alert";
import { Button } from "#/components/ui/button";
import { asApiError } from "#/lib/api-error";

interface ErrorCopy {
	title: string;
	message: string;
	hint?: string;
}

export function describeError(error: unknown): ErrorCopy {
	const api = asApiError(error);
	if (api !== null) {
		switch (api.status) {
			case 404:
				return {
					title: "Not found",
					message: "That record does not exist on this API.",
					hint: "It may have been cleared with the database. Head back and pick another run.",
				};
			case 409:
				return {
					title: "Action not allowed",
					message:
						"The run is not in a state that accepts this action — for example, its DDS is still withheld or a decision was already recorded.",
					hint: "Refresh the run to see its current state.",
				};
			case 422:
				return {
					title: "Invalid request",
					message: "The API rejected the payload for this request.",
					hint: `Operation: ${api.operation}`,
				};
			default:
				return {
					title: "API unreachable",
					message:
						api.status === null
							? `The ${api.operation} request could not reach the API.`
							: `The ${api.operation} request failed with status ${api.status}.`,
					hint: "Start the stack with pnpm dev (it starts Postgres and Redis), or run pnpm db:up && pnpm db:upgrade, then retry.",
				};
		}
	}
	const message = error instanceof Error ? error.message : String(error);
	return {
		title: "Something went wrong",
		message: message || "An unexpected error occurred.",
	};
}

export function ErrorState({
	error,
	onRetry,
}: {
	error: unknown;
	onRetry?: () => void;
}) {
	const copy = describeError(error);
	return (
		<Alert variant="destructive">
			<AlertTitle>{copy.title}</AlertTitle>
			<AlertDescription>
				<p>{copy.message}</p>
				{copy.hint && <p className="text-body-sm opacity-80">{copy.hint}</p>}
			</AlertDescription>
			{onRetry && (
				<AlertAction>
					<Button variant="outline" size="sm" onClick={onRetry}>
						<RotateCcwIcon data-icon="inline-start" />
						Retry
					</Button>
				</AlertAction>
			)}
		</Alert>
	);
}

/** Router `errorComponent`: resets both the query boundary and the route loader. */
export function RouteError({
	error,
	reset,
}: {
	error: unknown;
	reset?: () => void;
}) {
	const router = useRouter();
	const queryErrorResetBoundary = useQueryErrorResetBoundary();
	return (
		<div className="mx-auto w-full max-w-3xl p-4 md:p-6">
			<ErrorState
				error={error}
				onRetry={() => {
					queryErrorResetBoundary.reset();
					reset?.();
					router.invalidate();
				}}
			/>
		</div>
	);
}

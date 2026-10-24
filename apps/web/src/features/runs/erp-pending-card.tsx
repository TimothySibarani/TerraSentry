import { LandmarkIcon } from "lucide-react";

import { ErrorState } from "#/components/error-state";
import { SapStatusBadge } from "#/components/sap-panel";
import { Button } from "#/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "#/components/ui/card";
import { Spinner } from "#/components/ui/spinner";
import { useConfirmErpAction } from "#/features/runs/mutations";

/** An ERP change the run has planned but not applied (confirm mode, or a failed attempt). */
export function ErpPendingCard({
	runId,
	pending,
}: {
	runId: string;
	pending: "approved" | "blocked";
}) {
	const confirm = useConfirmErpAction(runId);
	const effect =
		pending === "blocked"
			? "block the vendor and set the purchasing block"
			: "set the vendor to approved and clear the purchasing block";
	return (
		<Card size="sm">
			<CardHeader>
				<CardTitle className="flex flex-wrap items-center gap-2">
					<LandmarkIcon aria-hidden="true" className="size-3.5" />
					ERP action waiting for you
					<SapStatusBadge status={pending} />
				</CardTitle>
				<CardDescription>
					Confirming will {effect} in SAP. Nothing has been changed yet.
				</CardDescription>
			</CardHeader>
			<CardContent className="flex flex-col gap-3">
				<div>
					<Button
						size="sm"
						disabled={confirm.isPending}
						onClick={() => confirm.mutate()}
					>
						{confirm.isPending && (
							<Spinner aria-label="Applying to SAP" data-icon="inline-start" />
						)}
						{pending === "blocked"
							? "Block vendor in SAP"
							: "Approve vendor in SAP"}
					</Button>
				</div>
				{confirm.error && <ErrorState error={confirm.error} />}
			</CardContent>
		</Card>
	);
}

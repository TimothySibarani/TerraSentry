import type { SapActionOut, SupplierSapOut } from "@terrasentry/api-client";
import { Link } from "@tanstack/react-router";
import { LandmarkIcon } from "lucide-react";

import { Badge } from "#/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "#/components/ui/card";
import { Separator } from "#/components/ui/separator";
import { formatDateTime } from "#/lib/format";

type SapBadgeVariant = "compliant" | "risk" | "destructive" | "outline";

const STATUS_LABEL: Record<string, { label: string; variant: SapBadgeVariant }> =
	{
		approved: { label: "Approved", variant: "compliant" },
		blocked: { label: "Blocked", variant: "risk" },
		failed: { label: "Failed", variant: "destructive" },
	};

export function SapStatusBadge({ status }: { status: string }) {
	const spec = STATUS_LABEL[status] ?? { label: status, variant: "outline" };
	return <Badge variant={spec.variant}>{spec.label}</Badge>;
}

export function SapModeBadge({ mode, real }: { mode: string; real: boolean }) {
	return (
		<Badge variant={real ? "compliant" : "review"}>
			{real ? `SAP ${mode} · hosted endpoint` : "SAP stub · schema-accurate"}
		</Badge>
	);
}

export function SapActionCard({
	action,
}: {
	action: SapActionOut | null | undefined;
}) {
	if (!action) {
		return (
			<Card size="sm">
				<CardHeader>
					<CardTitle className="flex items-center gap-2">
						<LandmarkIcon aria-hidden="true" className="size-3.5" />
						ERP action (SAP)
					</CardTitle>
					<CardDescription>
						No ERP action recorded yet. Ambiguous runs wait for the human
						decision before any vendor state changes.
					</CardDescription>
				</CardHeader>
			</Card>
		);
	}
	return (
		<Card size="sm">
			<CardHeader>
				<CardTitle className="flex flex-wrap items-center gap-2">
					<LandmarkIcon aria-hidden="true" className="size-3.5" />
					ERP action (SAP)
					<SapStatusBadge status={action.status} />
					<SapModeBadge mode={action.mode} real={action.real} />
				</CardTitle>
				<CardDescription>
					{action.error
						? `The ERP call failed; the compliance verdict stands. ${action.error}`
						: `Vendor ${action.vendor_id} reached ${action.status}${
								action.purchasing_block ? " with purchasing blocked" : ""
							}.`}
				</CardDescription>
			</CardHeader>
			<CardContent className="flex flex-col gap-2 text-body-sm">
				<div className="flex items-baseline justify-between gap-4">
					<span className="text-muted-foreground">Purchasing block</span>
					<span className="text-foreground">
						{action.purchasing_block ? "Set" : "Cleared"}
					</span>
				</div>
				<Separator />
				<div className="flex items-baseline justify-between gap-4">
					<span className="text-muted-foreground">Performed</span>
					<span className="text-foreground">
						{formatDateTime(action.performed_at)}
					</span>
				</div>
			</CardContent>
		</Card>
	);
}

export function SupplierSapCard({ sap }: { sap: SupplierSapOut | null }) {
	if (!sap) {
		return null;
	}
	const action = sap.last_action;
	return (
		<Card>
			<CardHeader>
				<CardTitle className="flex flex-wrap items-center gap-2">
					<LandmarkIcon aria-hidden="true" className="size-3.5" />
					ERP vendor status
					<SapStatusBadge status={sap.status} />
					<SapModeBadge mode={sap.mode} real={sap.real} />
				</CardTitle>
				<CardDescription>{sap.disclosure}</CardDescription>
			</CardHeader>
			<CardContent className="flex flex-col gap-2 text-body-sm">
				<div className="flex items-baseline justify-between gap-4">
					<span className="text-muted-foreground">Vendor ID</span>
					<span className="font-mono text-xs">{sap.vendor_id}</span>
				</div>
				<Separator />
				<div className="flex items-baseline justify-between gap-4">
					<span className="text-muted-foreground">Purchasing block</span>
					<span className="text-foreground">
						{sap.purchasing_block ? "Set" : "Cleared"}
					</span>
				</div>
				<Separator />
				<div className="flex items-baseline justify-between gap-4">
					<span className="text-muted-foreground">Last action</span>
					<span className="text-foreground">
						{action ? (
							<Link
								to="/runs/$runId"
								params={{ runId: action.run_id }}
								className="underline underline-offset-4"
							>
								{action.status} · {formatDateTime(action.performed_at)}
							</Link>
						) : (
							"—"
						)}
					</span>
				</div>
				{action?.error && (
					<p className="text-caption-mono-sm text-status-risk">
						{action.error}
					</p>
				)}
			</CardContent>
		</Card>
	);
}

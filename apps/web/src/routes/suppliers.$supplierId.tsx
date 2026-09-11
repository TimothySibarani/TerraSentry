import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowLeftIcon } from "lucide-react";
import { useMemo } from "react";

import { ErrorState } from "#/components/error-state";
import { MapView, type MapTone } from "#/components/map/map-view";
import { MetricCard } from "#/components/metric-card";
import { PageHeader } from "#/components/page-header";
import { Badge } from "#/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "#/components/ui/card";
import { Separator } from "#/components/ui/separator";
import { Skeleton } from "#/components/ui/skeleton";
import { decodeGeometry } from "#/features/runs/evidence";
import { supplierQuery } from "#/features/suppliers/queries";
import { formatNumber } from "#/lib/format";

export const Route = createFileRoute("/suppliers/$supplierId")({
	loader: ({ context, params }) =>
		context.queryClient.ensureQueryData(supplierQuery(params.supplierId)),
	component: SupplierDetailPage,
});

const ARCHETYPE_TONE: Record<string, MapTone> = {
	compliant: "compliant",
	high_risk: "risk",
	ambiguous: "review",
};

function SupplierDetailPage() {
	const { supplierId } = Route.useParams();
	const supplier = useQuery(supplierQuery(supplierId));
	const parcels = supplier.data?.parcels;
	const polygons = useMemo(
		() =>
			(parcels ?? []).flatMap((parcel) => {
				const geometry = decodeGeometry(parcel.geometry);
				if (!geometry) {
					return [];
				}
				return [
					{
						id: parcel.polygon_id,
						geometry,
						label: parcel.label,
						detail: `${parcel.region} · ${formatNumber(parcel.area_ha)} ha`,
						tone: ARCHETYPE_TONE[parcel.archetype] ?? "neutral",
					},
				];
			}),
		[parcels],
	);

	if (supplier.isPending) {
		return (
			<div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
				<Skeleton className="h-24" />
				<Skeleton className="h-40" />
				<Skeleton className="h-80" />
			</div>
		);
	}

	if (supplier.isError || !supplier.data) {
		return (
			<div className="mx-auto w-full max-w-3xl">
				<ErrorState
					error={supplier.error}
					onRetry={() => void supplier.refetch()}
				/>
			</div>
		);
	}

	const record = supplier.data;

	return (
		<div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
			<Link
				to="/suppliers"
				className="flex w-fit items-center gap-1 text-body-sm text-muted-foreground no-underline hover:text-foreground"
			>
				<ArrowLeftIcon aria-hidden="true" className="size-3.5" />
				All suppliers
			</Link>
			<PageHeader
				eyebrow="Supplier"
				title={record.legal_name}
				description={`${record.trading_name} · ${record.group}`}
				actions={
					<Badge variant={record.synthetic ? "review" : "compliant"}>
						{record.synthetic ? "synthetic data" : "real data"}
					</Badge>
				}
			/>

			<div className="grid gap-4 sm:grid-cols-3">
				<MetricCard
					label="Concession area"
					value={`${formatNumber(record.concession_area_ha)} ha`}
					hint={`${record.province} · ${record.kabupaten}`}
				/>
				<MetricCard
					label="Permit status"
					value={record.permit_status}
					hint={record.hgu_number ?? record.pbp_number ?? "No HGU/PBP on file"}
				/>
				<MetricCard
					label="Parcels"
					value={formatNumber(record.parcels.length)}
					hint="Polygons evaluated by the agents"
				/>
			</div>

			<div className="grid gap-6 lg:grid-cols-2">
				<Card>
					<CardHeader>
						<CardTitle>Identity</CardTitle>
						<CardDescription>
							Registry fields in real HGU/PBPH formats.
						</CardDescription>
					</CardHeader>
					<CardContent className="flex flex-col gap-2 text-body-sm">
						<Row label="Supplier ID" value={record.supplier_id} mono />
						<Row label="NIB" value={record.nib} mono />
						<Row label="NPWP" value={record.npwp} mono />
						<Row label="HGU number" value={record.hgu_number ?? "—"} mono />
						<Row label="PBP number" value={record.pbp_number ?? "—"} mono />
					</CardContent>
				</Card>
				<Card>
					<CardHeader>
						<CardTitle>Ownership & compliance</CardTitle>
						<CardDescription>
							Beneficial owners, certifications, and sanctions.
						</CardDescription>
					</CardHeader>
					<CardContent className="flex flex-col gap-3">
						<div className="flex flex-col gap-1">
							<p className="eyebrow-sm text-muted-foreground">
								Beneficial owners
							</p>
							<p className="text-body-sm text-muted-foreground">
								{record.beneficial_owners.join(", ") || "—"}
							</p>
						</div>
						<Separator />
						<div className="flex flex-col gap-1">
							<p className="eyebrow-sm text-muted-foreground">Certifications</p>
							<div className="flex flex-wrap gap-1">
								{record.certifications.length === 0 ? (
									<span className="text-body-sm text-muted-foreground">—</span>
								) : (
									record.certifications.map((certification) => (
										<Badge key={certification} variant="outline">
											{certification}
										</Badge>
									))
								)}
							</div>
						</div>
						<Separator />
						<div className="flex flex-col gap-1">
							<p className="eyebrow-sm text-muted-foreground">Sanctions</p>
							<div className="flex flex-wrap gap-1">
								{record.sanctions.length === 0 ? (
									<span className="text-body-sm text-muted-foreground">
										None
									</span>
								) : (
									record.sanctions.map((sanction) => (
										<Badge key={sanction} variant="risk">
											{sanction}
										</Badge>
									))
								)}
							</div>
						</div>
						<p className="text-caption-mono-sm text-muted-foreground">
							{record.disclosure}
						</p>
					</CardContent>
				</Card>
			</div>

			<Card>
				<CardHeader>
					<CardTitle>Parcels</CardTitle>
					<CardDescription>
						Polygon geometry from the synthetic concession dataset; the map
						colours parcels by their expected archetype.
					</CardDescription>
				</CardHeader>
				<CardContent className="flex flex-col gap-4">
					<ul className="flex flex-wrap gap-2">
						{record.parcels.map((parcel) => (
							<li key={parcel.polygon_id}>
								<span className="flex flex-wrap items-center gap-2 rounded-md border border-border px-3 py-2">
									<span className="font-mono text-xs">{parcel.polygon_id}</span>
									<span className="text-body-sm">{parcel.label}</span>
									<Badge
										variant={
											parcel.archetype === "high_risk"
												? "risk"
												: parcel.archetype === "ambiguous"
													? "review"
													: "compliant"
										}
									>
										{parcel.archetype}
									</Badge>
									{parcel.scenario && (
										<Badge variant="outline">{parcel.scenario}</Badge>
									)}
									<span className="text-caption-mono-sm text-muted-foreground">
										{formatNumber(parcel.area_ha)} ha
									</span>
								</span>
							</li>
						))}
					</ul>
					<MapView polygons={polygons} />
				</CardContent>
			</Card>
		</div>
	);
}

function Row({
	label,
	value,
	mono,
}: {
	label: string;
	value: string;
	mono?: boolean;
}) {
	return (
		<div className="flex items-baseline justify-between gap-4">
			<span className="text-muted-foreground">{label}</span>
			<span className={mono ? "font-mono text-xs" : "text-foreground"}>
				{value}
			</span>
		</div>
	);
}

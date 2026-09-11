import type { SupplierOut } from "@terrasentry/api-client";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { createColumnHelper } from "@tanstack/react-table";
import { SearchIcon } from "lucide-react";
import { useMemo } from "react";

import { DataTable, type TableFeatureSet } from "#/components/data-table";
import { ErrorState } from "#/components/error-state";
import { PageHeader } from "#/components/page-header";
import { Badge } from "#/components/ui/badge";
import { Input } from "#/components/ui/input";
import { Skeleton } from "#/components/ui/skeleton";
import { suppliersQuery } from "#/features/suppliers/queries";
import { formatNumber } from "#/lib/format";

export const Route = createFileRoute("/suppliers/")({
	validateSearch: (search: Record<string, unknown>): { q?: string } => ({
		q: typeof search.q === "string" ? search.q : undefined,
	}),
	loader: ({ context }) =>
		context.queryClient.ensureQueryData(suppliersQuery()),
	component: SuppliersPage,
});

const PERMIT_VARIANT: Record<
	string,
	"compliant" | "risk" | "review" | "outline"
> = {
	active: "compliant",
	suspended: "risk",
	expired: "risk",
	none: "outline",
};

const helper = createColumnHelper<TableFeatureSet, SupplierOut>();

const columns = helper.columns([
	helper.accessor("supplier_id", {
		header: "Supplier",
		cell: (info) => (
			<Link
				to="/suppliers/$supplierId"
				params={{ supplierId: info.getValue() }}
				className="font-mono text-xs text-foreground underline-offset-4 hover:underline"
			>
				{info.getValue()}
			</Link>
		),
	}),
	helper.accessor("legal_name", {
		header: "Legal name",
		cell: (info) => (
			<span className="flex flex-col">
				<span className="text-body-sm text-foreground">{info.getValue()}</span>
				<span className="text-caption-mono-sm text-muted-foreground">
					{info.row.original.trading_name}
				</span>
			</span>
		),
	}),
	helper.accessor("group", {
		header: "Group",
		cell: (info) => (
			<span className="text-body-sm text-muted-foreground">
				{info.getValue()}
			</span>
		),
	}),
	helper.accessor("province", {
		header: "Province",
		cell: (info) => (
			<span className="text-body-sm text-muted-foreground">
				{info.getValue()}
			</span>
		),
	}),
	helper.accessor("permit_status", {
		header: "Permit",
		cell: (info) => (
			<Badge variant={PERMIT_VARIANT[info.getValue()] ?? "outline"}>
				{info.getValue()}
			</Badge>
		),
	}),
	helper.accessor("concession_area_ha", {
		header: "Area (ha)",
		cell: (info) => (
			<span className="tabular-nums text-body-sm">
				{formatNumber(info.getValue())}
			</span>
		),
	}),
	helper.accessor("certifications", {
		header: "Certifications",
		enableSorting: false,
		cell: (info) =>
			info.getValue().length === 0 ? (
				<span className="text-muted-foreground">—</span>
			) : (
				<span className="flex gap-1">
					{info.getValue().map((certification) => (
						<Badge key={certification} variant="outline">
							{certification}
						</Badge>
					))}
				</span>
			),
	}),
	helper.accessor("synthetic", {
		header: "Data",
		cell: (info) =>
			info.getValue() ? (
				<Badge variant="review">synthetic</Badge>
			) : (
				<Badge variant="compliant">real</Badge>
			),
	}),
]);

function SuppliersPage() {
	const { q = "" } = Route.useSearch();
	const navigate = useNavigate({ from: Route.fullPath });
	const suppliers = useQuery(suppliersQuery());

	const filtered = useMemo(() => {
		const rows = suppliers.data ?? [];
		const needle = q.trim().toLowerCase();
		if (!needle) {
			return rows;
		}
		return rows.filter((supplier) =>
			[
				supplier.supplier_id,
				supplier.legal_name,
				supplier.trading_name,
				supplier.group,
				supplier.province,
				supplier.kabupaten,
			]
				.join(" ")
				.toLowerCase()
				.includes(needle),
		);
	}, [suppliers.data, q]);

	return (
		<div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
			<PageHeader
				eyebrow="Master data"
				title="Suppliers"
				description="The 50 synthetic operators behind the batch. Legality fields are generated in realistic HGU/PBPH formats and labelled synthetic everywhere."
				actions={
					<div className="relative w-full sm:w-72">
						<SearchIcon
							aria-hidden="true"
							className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
						/>
						<Input
							type="search"
							name="supplier-search"
							aria-label="Search suppliers"
							autoComplete="off"
							placeholder="Search name, group, province…"
							className="pl-8"
							value={q}
							onChange={(event) =>
								void navigate({
									search: { q: event.target.value },
									replace: true,
								})
							}
						/>
					</div>
				}
			/>
			<p
				aria-live="polite"
				className="text-caption-mono-sm text-muted-foreground"
			>
				{filtered.length} of {suppliers.data?.length ?? 0} suppliers
			</p>
			{suppliers.isPending && <Skeleton className="h-64" />}
			{suppliers.isError && (
				<ErrorState
					error={suppliers.error}
					onRetry={() => void suppliers.refetch()}
				/>
			)}
			{!suppliers.isPending && !suppliers.isError && (
				<DataTable
					caption="Suppliers"
					columns={columns}
					data={filtered}
					emptyMessage="No supplier matches that search."
					initialSorting={[{ id: "supplier_id", desc: false }]}
					getRowId={(supplier) => supplier.supplier_id}
				/>
			)}
		</div>
	);
}

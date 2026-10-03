import { createColumnHelper } from "@tanstack/react-table";
import type { EvidenceEntry } from "@terrasentry/api-client";
import { DataTable, type TableFeatureSet } from "#/components/data-table";
import { ProvenanceBadge } from "#/components/provenance-badge";
import { Badge } from "#/components/ui/badge";
import { formatDateTime, formatValue } from "#/lib/format";

const helper = createColumnHelper<TableFeatureSet, EvidenceEntry>();

const columns = helper.columns([
	helper.accessor("claim", {
		header: "Claim",
		cell: (info) => (
			<span
				id={info.row.original.evidence_id}
				className="font-mono text-xs text-foreground"
			>
				{info.getValue()}
			</span>
		),
	}),
	helper.accessor("source", {
		header: "Source",
		cell: (info) => <Badge variant="outline">{info.getValue()}</Badge>,
	}),
	helper.accessor("value", {
		header: "Value",
		enableSorting: false,
		cell: (info) => (
			<details className="max-w-96 text-body-sm text-muted-foreground">
				<summary className="cursor-pointer">
					{formatValue(info.getValue())}
				</summary>
				<pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">
					{JSON.stringify(
						{ value: info.getValue(), artifact: info.row.original.artifact },
						null,
						2,
					)}
				</pre>
			</details>
		),
	}),
	helper.accessor("unit", {
		header: "Unit",
		cell: (info) => (
			<span className="text-muted-foreground">{info.getValue() ?? "—"}</span>
		),
	}),
	helper.accessor("retrieved_at", {
		header: "Retrieved",
		cell: (info) => (
			<span className="text-caption-mono-sm text-muted-foreground">
				{formatDateTime(info.getValue())}
			</span>
		),
	}),
	helper.display({
		id: "flags",
		header: "Flags",
		cell: (info) => {
			const entry = info.row.original;
			return (
				<span className="flex gap-1">
					{entry.cached && <Badge variant="secondary">cached</Badge>}
					<ProvenanceBadge provenance={entry.provenance} />
				</span>
			);
		},
	}),
]);

export function EvidenceTable({
	entries,
}: {
	entries: ReadonlyArray<EvidenceEntry>;
}) {
	return (
		<DataTable
			caption="Evidence ledger"
			columns={columns}
			data={entries}
			emptyMessage="No evidence recorded for this run."
			initialSorting={[{ id: "claim", desc: false }]}
			getRowId={(entry) => entry.evidence_id}
		/>
	);
}

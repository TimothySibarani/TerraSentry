import { Badge } from "#/components/ui/badge";

const LABELS: Record<string, string> = {
	synthetic: "Synthetic",
	supplier_declared: "Supplier declared",
	document_extracted: "Document extracted",
	sap_import: "SAP imported",
	real_source: "Source observation",
	operator_configured: "Operator configured",
	derived: "Derived",
	legacy_unknown: "Legacy provenance unknown",
};

export function ProvenanceBadge({ provenance }: { provenance?: string }) {
	return (
		<Badge variant={provenance === "synthetic" ? "review" : "outline"}>
			{LABELS[provenance ?? "legacy_unknown"] ?? LABELS.legacy_unknown}
		</Badge>
	);
}

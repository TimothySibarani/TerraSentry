import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import type { ImportResult } from "@terrasentry/api-client";
import { FileUpIcon, UploadIcon } from "lucide-react";
import { useRef, useState } from "react";

import { ErrorState } from "#/components/error-state";
import { PageHeader } from "#/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "#/components/ui/alert";
import { Button } from "#/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "#/components/ui/card";
import { Spinner } from "#/components/ui/spinner";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "#/components/ui/table";
import {
	PORTFOLIO_MAX_BYTES,
	PORTFOLIO_TEMPLATE_CSV,
	type PortfolioPreview,
	previewPortfolio,
} from "#/features/intake/portfolio";
import { useImportPortfolio } from "#/features/intake/queries";
import { useCreateBatch } from "#/features/runs/mutations";
import { cn } from "#/lib/utils";

export const Route = createFileRoute("/suppliers/import")({
	head: () => ({ meta: [{ title: "Import suppliers — TerraSentry" }] }),
	component: ImportSuppliersPage,
});

/** Agent investigations are capped server-side; fast screening takes the whole file. */
const AGENT_BATCH_LIMIT = 50;

function formatSize(bytes: number): string {
	return bytes < 1024 * 1024
		? `${Math.max(1, Math.round(bytes / 1024))} KB`
		: `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function downloadTemplate() {
	const url = URL.createObjectURL(
		new Blob([PORTFOLIO_TEMPLATE_CSV], { type: "text/csv" }),
	);
	const link = document.createElement("a");
	link.href = url;
	link.download = "portfolio-template.csv";
	link.click();
	URL.revokeObjectURL(url);
}

function ImportSuppliersPage() {
	const navigate = useNavigate();
	const inputRef = useRef<HTMLInputElement>(null);
	const [file, setFile] = useState<File | null>(null);
	const [preview, setPreview] = useState<PortfolioPreview | null>(null);
	const [dragging, setDragging] = useState(false);
	const [result, setResult] = useState<ImportResult | null>(null);
	const importer = useImportPortfolio();
	const screen = useCreateBatch();

	const choose = async (next: File | undefined) => {
		setResult(null);
		importer.reset();
		screen.reset();
		if (!next) {
			return;
		}
		setFile(next);
		const checked =
			next.size > PORTFOLIO_MAX_BYTES
				? ({
						kind: "unsupported",
						rows: 0,
						problems: [
							`${formatSize(next.size)} is over the ${formatSize(PORTFOLIO_MAX_BYTES)} limit.`,
						],
					} satisfies PortfolioPreview)
				: previewPortfolio(next.name, await next.text());
		setPreview(checked);
	};

	const upload = () => {
		if (!file) {
			return;
		}
		importer.mutate(file, { onSuccess: setResult });
	};

	const screenAll = (mode: "screening" | "agent") => {
		const recordIds = result?.created.map((record) => record.record_id) ?? [];
		screen.mutate(
			{ record_ids: recordIds, mode },
			{
				onSuccess: (batch) =>
					void navigate({
						to: "/batch/$batchId",
						params: { batchId: batch.run_id },
					}),
			},
		);
	};

	const blocked = preview === null || preview.problems.length > 0;
	const created = result?.created.length ?? 0;

	return (
		<div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
			<PageHeader
				eyebrow="Portfolio"
				title="Import suppliers"
				description="Upload a CSV or GeoJSON of the plots your suppliers farm or harvest. Each valid row becomes a record to screen; a row that is rejected is listed with the reason. Legality fields are what the supplier declared."
				actions={
					<Button variant="outline" size="sm" onClick={downloadTemplate}>
						Download CSV template
					</Button>
				}
			/>

			<Card>
				<CardHeader>
					<CardTitle>1. Choose a file</CardTitle>
					<CardDescription>
						CSV with a wkt column (or lat and lon for a point of 4 ha or less),
						or a GeoJSON FeatureCollection. Up to 500 rows and 5 MB.
					</CardDescription>
				</CardHeader>
				<CardContent className="flex flex-col gap-4">
					<button
						type="button"
						onClick={() => inputRef.current?.click()}
						onDragOver={(event) => {
							event.preventDefault();
							setDragging(true);
						}}
						onDragLeave={() => setDragging(false)}
						onDrop={(event) => {
							event.preventDefault();
							setDragging(false);
							void choose(event.dataTransfer.files[0]);
						}}
						className={cn(
							"flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-canvas-soft/40 px-6 py-10 text-center transition-colors hover:bg-canvas-soft focus-visible:outline-2 focus-visible:outline-ring",
							dragging && "border-foreground bg-canvas-soft",
						)}
					>
						<FileUpIcon
							aria-hidden="true"
							className="size-6 text-muted-foreground"
						/>
						<span className="text-body-sm text-foreground">
							{file ? file.name : "Drop a file here, or choose one"}
						</span>
						<span className="text-caption-mono-sm text-muted-foreground">
							{file
								? `${formatSize(file.size)}${preview ? ` · ${preview.rows} row${preview.rows === 1 ? "" : "s"}` : ""}`
								: ".csv, .geojson or .json"}
						</span>
					</button>
					<input
						ref={inputRef}
						type="file"
						accept=".csv,.geojson,.json,text/csv,application/geo+json,application/json"
						className="sr-only"
						aria-label="Supplier portfolio file"
						onChange={(event) => void choose(event.target.files?.[0])}
					/>
					{preview && preview.problems.length > 0 && (
						<Alert variant="destructive">
							<AlertTitle>This file can't be imported yet</AlertTitle>
							<AlertDescription>
								<ul className="list-disc pl-5">
									{preview.problems.map((problem) => (
										<li key={problem}>{problem}</li>
									))}
								</ul>
							</AlertDescription>
						</Alert>
					)}
					{importer.error && <ErrorState error={importer.error} />}
					<div>
						<Button disabled={blocked || importer.isPending} onClick={upload}>
							{importer.isPending ? (
								<Spinner aria-label="Importing" data-icon="inline-start" />
							) : (
								<UploadIcon data-icon="inline-start" aria-hidden="true" />
							)}
							{preview && !blocked
								? `Import ${preview.rows} row${preview.rows === 1 ? "" : "s"}`
								: "Import"}
						</Button>
					</div>
				</CardContent>
			</Card>

			{result && (
				<Card>
					<CardHeader>
						<CardTitle>2. Review the import</CardTitle>
						<CardDescription>
							{created} of {result.total_rows} rows imported
							{result.errors.length > 0
								? `; ${result.errors.length} rejected`
								: ""}
							.
						</CardDescription>
					</CardHeader>
					<CardContent className="flex flex-col gap-4">
						{result.errors.length > 0 && (
							<div className="overflow-hidden rounded-lg border border-border">
								<Table>
									<caption className="sr-only">Rejected rows</caption>
									<TableHeader>
										<TableRow>
											<TableHead>Row</TableHead>
											<TableHead>Field</TableHead>
											<TableHead>Why it was rejected</TableHead>
										</TableRow>
									</TableHeader>
									<TableBody>
										{result.errors.map((error) => (
											<TableRow key={`${error.row}-${error.field}`}>
												<TableCell className="tabular-nums">
													{error.row}
												</TableCell>
												<TableCell className="font-mono text-xs">
													{error.field}
												</TableCell>
												<TableCell className="text-body-sm">
													{error.message}
												</TableCell>
											</TableRow>
										))}
									</TableBody>
								</Table>
							</div>
						)}
						{created === 0 ? (
							<p className="text-body-sm text-muted-foreground">
								Nothing was imported. Fix the rows above and upload the file
								again.
							</p>
						) : (
							<>
								<p className="text-body-sm text-muted-foreground">
									Compliant results are approved in SAP automatically. Ambiguous
									and high-risk results wait in{" "}
									<Link to="/review" className="underline underline-offset-4">
										Needs review
									</Link>{" "}
									until you decide.
								</p>
								<div className="flex flex-wrap items-center gap-2">
									<Button
										disabled={screen.isPending}
										onClick={() => screenAll("screening")}
									>
										{screen.isPending && (
											<Spinner
												aria-label="Starting screening"
												data-icon="inline-start"
											/>
										)}
										Screen {created} supplier{created === 1 ? "" : "s"}
									</Button>
									<Button
										variant="outline"
										disabled={screen.isPending || created > AGENT_BATCH_LIMIT}
										onClick={() => screenAll("agent")}
									>
										Investigate with agents
									</Button>
									{created > AGENT_BATCH_LIMIT && (
										<span className="text-caption-mono-sm text-muted-foreground">
											Agent runs take up to {AGENT_BATCH_LIMIT} at a time
										</span>
									)}
								</div>
								{screen.error && <ErrorState error={screen.error} />}
							</>
						)}
					</CardContent>
				</Card>
			)}
		</div>
	);
}

import { useQuery } from "@tanstack/react-query";
import { DownloadIcon } from "lucide-react";
import { useState } from "react";

import {
	Alert,
	AlertAction,
	AlertDescription,
	AlertTitle,
} from "#/components/ui/alert";
import { Button } from "#/components/ui/button";
import { ScrollArea } from "#/components/ui/scroll-area";
import { Skeleton } from "#/components/ui/skeleton";
import { Spinner } from "#/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "#/components/ui/tabs";
import { runDdsQuery, runDdsXmlQuery } from "#/features/runs/queries";
import { runApi } from "#/lib/api";
import { prettyJson } from "#/lib/format";

export function DdsDownloadButton({
	runId,
	disabled,
}: {
	runId: string;
	disabled?: boolean;
}) {
	const [downloading, setDownloading] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const download = async () => {
		setDownloading(true);
		setError(null);
		try {
			const xml = await runApi((api) => api.getRunDdsXml(runId));
			const blob = new Blob([xml], { type: "application/xml" });
			const url = URL.createObjectURL(blob);
			const anchor = document.createElement("a");
			anchor.href = url;
			anchor.download = `${runId}.dds.xml`;
			document.body.append(anchor);
			anchor.click();
			anchor.remove();
			URL.revokeObjectURL(url);
		} catch {
			setError("The DDS could not be downloaded.");
		} finally {
			setDownloading(false);
		}
	};

	return (
		<div className="flex flex-col items-end gap-1">
			<Button
				variant="outline"
				size="sm"
				disabled={disabled || downloading}
				onClick={download}
			>
				{downloading ? (
					<Spinner aria-label="Downloading DDS" data-icon="inline-start" />
				) : (
					<DownloadIcon data-icon="inline-start" aria-hidden="true" />
				)}
				DDS XML
			</Button>
			{error && (
				<p className="text-caption-mono-sm text-destructive">{error}</p>
			)}
		</div>
	);
}

export function DdsPanel({
	runId,
	released,
}: {
	runId: string;
	released: boolean;
}) {
	const [format, setFormat] = useState("json");
	const json = useQuery(runDdsQuery(runId, released));
	const xml = useQuery(runDdsXmlQuery(runId, released && format === "xml"));

	if (!released) {
		return (
			<Alert>
				<AlertTitle>DDS withheld</AlertTitle>
				<AlertDescription>
					The document is stored as <code>pending_assessment</code> until a
					human decision releases it. This is the designed HITL gate, not an
					error.
				</AlertDescription>
			</Alert>
		);
	}

	return (
		<Tabs value={format} onValueChange={(value) => setFormat(value as string)}>
			<TabsList variant="line">
				<TabsTrigger value="json">JSON</TabsTrigger>
				<TabsTrigger value="xml">XML</TabsTrigger>
			</TabsList>
			<TabsContent value="json">
				{json.isPending ? (
					<Skeleton className="h-64" />
				) : json.isError ? (
					<Alert variant="destructive">
						<AlertTitle>Could not load the DDS</AlertTitle>
						<AlertDescription>
							The API did not return the JSON document.
						</AlertDescription>
						<AlertAction>
							<Button
								variant="outline"
								size="sm"
								onClick={() => void json.refetch()}
							>
								Retry
							</Button>
						</AlertAction>
					</Alert>
				) : (
					<ScrollArea className="h-96 rounded-lg border border-border bg-canvas-soft">
						<pre className="p-4 text-[11px] leading-relaxed text-foreground">
							{prettyJson(json.data)}
						</pre>
					</ScrollArea>
				)}
			</TabsContent>
			<TabsContent value="xml">
				{xml.isPending ? (
					<Skeleton className="h-64" />
				) : xml.isError ? (
					<Alert variant="destructive">
						<AlertTitle>Could not load the DDS XML</AlertTitle>
						<AlertDescription>
							The EUDR Information System payload is unavailable for this run.
						</AlertDescription>
						<AlertAction>
							<Button
								variant="outline"
								size="sm"
								onClick={() => void xml.refetch()}
							>
								Retry
							</Button>
						</AlertAction>
					</Alert>
				) : (
					<ScrollArea className="h-96 rounded-lg border border-border bg-canvas-soft">
						<pre className="p-4 text-[11px] leading-relaxed whitespace-pre-wrap text-foreground">
							{xml.data}
						</pre>
					</ScrollArea>
				)}
			</TabsContent>
		</Tabs>
	);
}

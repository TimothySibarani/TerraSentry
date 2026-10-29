import type { AdverseMediaReport } from "@terrasentry/api-client";

import { Alert, AlertDescription, AlertTitle } from "#/components/ui/alert";
import { Badge } from "#/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "#/components/ui/card";

/**
 * Cited adverse-media context from the legality analyst. It is background for the reviewer and is
 * never part of the rubric, the evidence ledger, or the DDS.
 */
export function AdverseMediaCard({ report }: { report: AdverseMediaReport }) {
	return (
		<Card>
			<CardHeader>
				<div className="flex flex-wrap items-center gap-2">
					<CardTitle>Adverse media</CardTitle>
					<Badge variant="outline">Context only, not scored</Badge>
					{report.synthetic && <Badge variant="review">Simulated</Badge>}
					{report.cached && <Badge variant="outline">Cached</Badge>}
				</div>
				<CardDescription>
					Public reporting about {report.subject}
					{report.country ? ` (${report.country})` : ""}, found by{" "}
					{report.model}. Check each source before relying on it.
				</CardDescription>
			</CardHeader>
			<CardContent className="flex flex-col gap-4">
				{report.status === "unavailable" ? (
					<Alert>
						<AlertTitle>Adverse media unavailable</AlertTitle>
						<AlertDescription>
							{report.error ?? "The search did not return a result."}
						</AlertDescription>
					</Alert>
				) : (
					<>
						{report.summary && (
							<p className="text-body-sm text-muted-foreground">
								{report.summary}
							</p>
						)}
						{report.findings.length === 0 ? (
							<p className="text-body-sm text-muted-foreground">
								No cited findings.
							</p>
						) : (
							<ul className="flex flex-col gap-3">
								{report.findings.map((finding) => (
									<li key={finding.claim} className="flex flex-col gap-1">
										<p className="text-body-sm">{finding.claim}</p>
										<ul className="flex flex-col gap-0.5">
											{finding.citations.map((citation) => (
												<li key={citation.url} className="text-body-sm">
													<a
														href={citation.url}
														target="_blank"
														rel="noreferrer noopener"
														className="text-primary underline-offset-4 hover:underline"
													>
														{citation.title || citation.url}
													</a>
													{citation.published && (
														<span className="text-muted-foreground">
															{" "}
															· {citation.published}
														</span>
													)}
												</li>
											))}
										</ul>
									</li>
								))}
							</ul>
						)}
					</>
				)}
				{report.disclosure && (
					<p className="text-body-sm text-muted-foreground">
						{report.disclosure}
					</p>
				)}
			</CardContent>
		</Card>
	);
}

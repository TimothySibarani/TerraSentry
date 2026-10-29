import { ArrowRightIcon } from "lucide-react";

import { Badge } from "#/components/ui/badge";
import { SOURCE_TOOLS } from "./pipeline";

const INPUTS: ReadonlyArray<[string, string]> = [
	["Plot geometry", "Polygon or point, drawn, pasted or seeded"],
	["Supplier & permit", "Legal name, NIB, HGU/PBPH permit, status, holder"],
	["Consignment", "Commodity, HS heading, weight, harvest year"],
	["EU operator", "Who files the DDS (Settings)"],
];

const DECISION: ReadonlyArray<[string, string]> = [
	["Rubric", "Deterministic score and verdict from the evidence, no model"],
	["Verifier", "Re-derives every metric and checks the deep dives ran"],
	["Person", "High-risk and ambiguous verdicts wait for a decision"],
	["DDS + SAP", "Statement released; vendor approved or blocked"],
];

function Column({
	title,
	children,
}: {
	title: string;
	children: React.ReactNode;
}) {
	return (
		<section aria-label={title} className="flex min-w-0 flex-col gap-2">
			<h4 className="eyebrow-sm text-muted-foreground">{title}</h4>
			<ul className="flex flex-col gap-2">{children}</ul>
		</section>
	);
}

function Item({ title, detail }: { title: string; detail: React.ReactNode }) {
	return (
		<li className="flex flex-col gap-0.5 rounded-lg border border-border bg-canvas-soft/40 p-2.5">
			<span className="text-body-sm">{title}</span>
			<span className="text-xs text-muted-foreground">{detail}</span>
		</li>
	);
}

/** What the app accepts, which tool reads each part, which external dataset it checks, and who decides. */
export function HowItWorks() {
	const datasets = [
		...new Set(SOURCE_TOOLS.flatMap((tool) => tool.datasets)),
	].filter((name) => name !== "Context layer summary");
	return (
		<div className="grid gap-4 md:grid-cols-2 xl:grid-cols-[1fr_auto_1.3fr_auto_1fr_auto_1fr] xl:items-start">
			<Column title="1 · You give">
				{INPUTS.map(([title, detail]) => (
					<Item key={title} title={title} detail={detail} />
				))}
			</Column>
			<Arrow />
			<Column title="2 · Agents call tools">
				{SOURCE_TOOLS.map((tool) => (
					<Item
						key={tool.name}
						title={tool.name}
						detail={
							<>
								{tool.agent} · reads {tool.reads.toLowerCase()}
								{tool.deepDive && (
									<Badge variant="review" className="ml-1">
										deep dive
									</Badge>
								)}
							</>
						}
					/>
				))}
			</Column>
			<Arrow />
			<Column title="3 · Checked against">
				{datasets.map((name) => (
					<Item
						key={name}
						title={name}
						detail={name.startsWith("Sonar") ? "context, never scored" : "live"}
					/>
				))}
				<Item
					title="Declared record"
					detail="Supplier and consignment as given, labelled synthetic for seeds"
				/>
			</Column>
			<Arrow />
			<Column title="4 · Decided by">
				{DECISION.map(([title, detail]) => (
					<Item key={title} title={title} detail={detail} />
				))}
			</Column>
		</div>
	);
}

function Arrow() {
	return (
		<ArrowRightIcon
			aria-hidden="true"
			className="hidden size-4 self-center text-muted-foreground xl:block"
		/>
	);
}

import {
	DatabaseIcon,
	FlameIcon,
	LandmarkIcon,
	LayersIcon,
	LoaderCircleIcon,
	PackageIcon,
	TreesIcon,
} from "lucide-react";
import { Badge } from "#/components/ui/badge";
import { cn } from "#/lib/utils";
import type { AgentRun } from "./agent-run";
import { type DatasetCard, datasetCards, splitCards } from "./work-context";

const ICON: Record<string, typeof DatabaseIcon> = {
	get_tree_cover_loss: TreesIcon,
	get_fire_hotspots: FlameIcon,
	get_legality_record: LandmarkIcon,
	get_consignment: PackageIcon,
	check_concession_overlap: LandmarkIcon,
};

/** What the agents are working on: the plot and the datasets they have actually read so far. */
export function WorkContext({
	run,
	fallback,
	onSelect,
	onOpenMap,
}: {
	run: AgentRun;
	onOpenMap?: () => void;
	fallback: {
		record_id?: string | null;
		supplier_id?: string | null;
		polygon_id?: string | null;
	};
	onSelect: (agent: string, step?: string) => void;
}) {
	const record = run.config.record;
	const cards = datasetCards(run);
	const { declared, checked } = splitCards(cards);
	const facts: [string, string | undefined][] = [
		["Record", record.record_id ?? fallback.record_id ?? undefined],
		["Supplier", record.supplier_id ?? fallback.supplier_id ?? undefined],
		["Plot", record.polygon_id ?? fallback.polygon_id ?? undefined],
		["Region", record.region],
		[
			"Area",
			record.area_ha !== undefined
				? `${record.area_ha.toLocaleString("en-GB", { maximumFractionDigits: 2 })} ha`
				: undefined,
		],
		["Commodity", record.commodity?.replaceAll("_", " ")],
		["HS", record.hs_heading],
	];
	return (
		<section aria-label="Work context" className="flex flex-col gap-3">
			<div className="flex flex-wrap items-center justify-between gap-2">
				<h3 className="eyebrow-sm text-muted-foreground">Work context</h3>
				{onOpenMap && (
					<button
						type="button"
						onClick={onOpenMap}
						className="text-caption-mono-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
					>
						Open plot on map
					</button>
				)}
			</div>
			<dl className="flex flex-wrap gap-x-6 gap-y-1 text-body-sm">
				{facts
					.filter(([, value]) => value)
					.map(([label, value]) => (
						<div key={label} className="flex gap-2">
							<dt className="text-muted-foreground">{label}</dt>
							<dd className="font-mono text-xs leading-5">{value}</dd>
						</div>
					))}
			</dl>
			{cards.length === 0 ? (
				<p className="text-body-sm text-muted-foreground">
					No dataset has been read yet. Cards appear as each specialist's tool
					call returns.
				</p>
			) : (
				<div className="flex flex-col gap-3">
					{(
						[
							["Declared by the supplier", declared],
							["Checked against", checked],
						] as const
					).map(
						([heading, group]) =>
							group.length > 0 && (
								<div key={heading} className="flex flex-col gap-2">
									<h4 className="text-caption-mono-sm text-muted-foreground">
										{heading}
									</h4>
									<ul
										aria-label={heading}
										aria-live="polite"
										className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4"
									>
										{group.map((card) => (
											<li key={card.key}>
												<DatasetTile card={card} onSelect={onSelect} />
											</li>
										))}
									</ul>
								</div>
							),
					)}
				</div>
			)}
		</section>
	);
}

function DatasetTile({
	card,
	onSelect,
}: {
	card: DatasetCard;
	onSelect: (agent: string, step?: string) => void;
}) {
	const Icon =
		card.status === "running"
			? LoaderCircleIcon
			: (ICON[card.key] ??
				(card.key.startsWith("layer:") ? LayersIcon : DatabaseIcon));
	return (
		<button
			type="button"
			onClick={() => onSelect(card.agent, card.stepId)}
			className={cn(
				"flex h-full w-full flex-col gap-1 rounded-lg border bg-canvas-soft/40 p-3 text-left outline-none hover:bg-canvas-soft focus-visible:ring-2 focus-visible:ring-ring/50 motion-safe:animate-in motion-safe:fade-in",
				card.status === "error" && "border-status-risk/50",
				card.status === "running" && "border-accent-breeze/50",
			)}
		>
			<span className="flex items-center gap-2 text-body-sm">
				<Icon
					aria-hidden="true"
					className={cn(
						"size-3.5 shrink-0 text-muted-foreground",
						card.status === "running" &&
							"text-accent-breeze motion-safe:animate-spin",
					)}
				/>
				<span className="truncate">{card.title}</span>
				{card.synthetic && <Badge variant="review">synthetic</Badge>}
				{card.cached !== undefined && (
					<Badge variant="outline" className="ml-auto">
						{card.cached ? "cached" : "live"}
					</Badge>
				)}
			</span>
			<span
				className={cn(
					"text-body-sm tabular-nums",
					card.status === "error" ? "text-status-risk" : "text-foreground",
				)}
			>
				{card.metric}
			</span>
			<span className="truncate font-mono text-xs text-muted-foreground">
				{card.source}
				{card.window ? ` · ${card.window}` : ""}
			</span>
			<span className="text-xs text-muted-foreground">
				read by {card.agent.replaceAll("_", " ")}
			</span>
		</button>
	);
}

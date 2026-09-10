import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import {
	ArrowRightIcon,
	FlameIcon,
	MapIcon,
	PlayIcon,
	PlusIcon,
	SatelliteIcon,
	ScaleIcon,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "#/components/ui/alert";
import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "#/components/ui/card";
import {
	Empty,
	EmptyContent,
	EmptyDescription,
	EmptyHeader,
	EmptyMedia,
	EmptyTitle,
} from "#/components/ui/empty";
import { Separator } from "#/components/ui/separator";
import { Skeleton } from "#/components/ui/skeleton";
import { Spinner } from "#/components/ui/spinner";
import { healthQuery } from "#/features/health/queries";

export const Route = createFileRoute("/")({
	loader: ({ context }) => context.queryClient.ensureQueryData(healthQuery()),
	component: Home,
});

const capabilities = [
	{
		title: "Geospatial",
		detail: "Forest-loss history per parcel from GFW/Hansen imagery.",
		icon: MapIcon,
	},
	{
		title: "Thermal",
		detail: "Active fire detections near the plot from NASA FIRMS.",
		icon: FlameIcon,
	},
	{
		title: "Legality",
		detail: "DDS readiness and supply-chain checks against HGU records.",
		icon: ScaleIcon,
	},
];

function Home() {
	const { data, isPending } = useQuery(healthQuery());
	const online = data?.online ?? false;

	return (
		<main>
			<section className="mx-auto w-full max-w-5xl px-6 pt-16 pb-16 md:pt-24">
				<p className="eyebrow text-muted-foreground">EUDR due diligence</p>
				<h1 className="mt-4 max-w-3xl text-display-md text-foreground md:text-display-xl">
					Verify every parcel before it ships.
				</h1>
				<p className="mt-6 max-w-2xl text-body-lg text-body">
					TerraSentry runs geospatial, thermal, and legality checks for each
					supplier lot, cites every claim, and routes anything ambiguous to a
					human reviewer.
				</p>
				<div className="mt-8 flex flex-wrap items-center gap-3">
					<Button variant="outline">
						<PlayIcon data-icon="inline-start" />
						Start a due-diligence run
					</Button>
					<Button variant="ghost">
						View the 50-record batch
						<ArrowRightIcon data-icon="inline-end" />
					</Button>
				</div>
			</section>

			<section className="mx-auto w-full max-w-5xl px-6 pb-16">
				<Card className="max-w-xl">
					<CardHeader>
						<CardTitle>System status</CardTitle>
						<CardDescription>
							Live health check against the FastAPI backend.
						</CardDescription>
					</CardHeader>
					<CardContent className="flex flex-col gap-4">
						{isPending ? (
							<div className="flex items-center gap-3">
								<Spinner className="size-4 text-muted-foreground" />
								<Skeleton className="h-5 w-40" />
							</div>
						) : (
							<div className="flex flex-wrap items-center gap-3">
								{online ? (
									<Badge variant="compliant">Online</Badge>
								) : (
									<Badge variant="risk">Offline</Badge>
								)}
								<span className="text-body-sm text-muted-foreground">
									{online
										? `API reports "${data?.status}".`
										: "API unreachable — showing the offline fallback."}
								</span>
							</div>
						)}
						{!isPending && !online && (
							<Alert variant="destructive">
								<AlertTitle>Backend not reachable</AlertTitle>
								<AlertDescription>
									Start the API with pnpm dev or docker compose up, then reload.
								</AlertDescription>
							</Alert>
						)}
					</CardContent>
				</Card>
			</section>

			<section
				id="capabilities"
				className="mx-auto w-full max-w-5xl px-6 pb-16"
			>
				<p className="eyebrow text-muted-foreground">Capabilities</p>
				<h2 className="mt-3 text-display-sm text-foreground">
					Three checks, one verdict, every claim cited.
				</h2>
				<div className="mt-8 grid gap-4 md:grid-cols-3">
					{capabilities.map(({ title, detail, icon: Icon }) => (
						<Card key={title}>
							<CardHeader>
								<CardTitle className="flex items-center gap-2">
									<Icon className="size-4 text-muted-foreground" />
									{title}
								</CardTitle>
								<CardDescription>{detail}</CardDescription>
							</CardHeader>
							<CardContent>
								<Separator />
								<p className="mt-3 text-body-sm text-muted-foreground">
									Evidence cached per source and replayable.
								</p>
							</CardContent>
						</Card>
					))}
				</div>
			</section>

			<section id="runs" className="mx-auto w-full max-w-5xl px-6 pb-24">
				<p className="eyebrow text-muted-foreground">Runs</p>
				<Empty className="mt-4">
					<EmptyHeader>
						<EmptyMedia variant="icon">
							<SatelliteIcon />
						</EmptyMedia>
						<EmptyTitle>No runs yet</EmptyTitle>
						<EmptyDescription>
							Start a live scenario or queue the 50-record batch to populate the
							cockpit.
						</EmptyDescription>
					</EmptyHeader>
					<EmptyContent>
						<Button variant="outline" size="sm">
							<PlusIcon data-icon="inline-start" />
							New run
						</Button>
					</EmptyContent>
				</Empty>
			</section>
		</main>
	);
}

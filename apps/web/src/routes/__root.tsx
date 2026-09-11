import { TanStackDevtools } from "@tanstack/react-devtools";
import type { QueryClient } from "@tanstack/react-query";
import {
	createRootRouteWithContext,
	HeadContent,
	Link,
	Scripts,
} from "@tanstack/react-router";
import { TanStackRouterDevtoolsPanel } from "@tanstack/react-router-devtools";
import { CompassIcon } from "lucide-react";
import type { ReactNode } from "react";
import TanStackQueryDevtools from "../integrations/tanstack-query/devtools";
import appCss from "../styles.css?url";
import { RouteError } from "#/components/error-state";
import { AppSidebar } from "#/components/layout/app-sidebar";
import { Button } from "#/components/ui/button";
import {
	Empty,
	EmptyContent,
	EmptyDescription,
	EmptyHeader,
	EmptyMedia,
	EmptyTitle,
} from "#/components/ui/empty";
import { Separator } from "#/components/ui/separator";
import {
	SidebarInset,
	SidebarProvider,
	SidebarTrigger,
} from "#/components/ui/sidebar";
import { Skeleton } from "#/components/ui/skeleton";
import { TooltipProvider } from "#/components/ui/tooltip";

interface MyRouterContext {
	queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<MyRouterContext>()({
	head: () => ({
		meta: [
			{
				charSet: "utf-8",
			},
			{
				name: "viewport",
				content: "width=device-width, initial-scale=1",
			},
			{
				title: "TerraSentry — EUDR due-diligence cockpit",
			},
			{
				name: "description",
				content:
					"TerraSentry verifies EUDR supplier lots against satellite, thermal, and legality evidence, with every claim cited.",
			},
			{
				name: "theme-color",
				content: "#0a0a0a",
			},
		],
		links: [
			{
				rel: "stylesheet",
				href: appCss,
			},
		],
	}),
	shellComponent: RootDocument,
	errorComponent: RouteError,
	notFoundComponent: NotFound,
	pendingComponent: RoutePending,
});

function RootDocument({ children }: { children: ReactNode }) {
	return (
		<html lang="en" className="dark">
			<head>
				<HeadContent />
			</head>
			<body className="min-h-dvh bg-background">
				<a
					href="#main"
					className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:rounded-full focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground"
				>
					Skip to content
				</a>
				<TooltipProvider>
					<SidebarProvider>
						<AppSidebar />
						<SidebarInset id="main" className="min-h-dvh">
							<header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b border-border bg-background/80 px-3 backdrop-blur md:px-4">
								<SidebarTrigger aria-label="Toggle navigation" />
								<Separator orientation="vertical" className="h-4" />
								<Link
									to="/"
									className="text-body-sm text-foreground no-underline md:hidden"
								>
									TerraSentry
								</Link>
								<p className="hidden text-caption-mono-sm text-muted-foreground md:block">
									Due-diligence cockpit
								</p>
							</header>
							<div className="flex-1 px-4 py-6 md:px-6">{children}</div>
						</SidebarInset>
					</SidebarProvider>
				</TooltipProvider>
				{import.meta.env.DEV && (
					<TanStackDevtools
						config={{
							position: "bottom-right",
						}}
						plugins={[
							{
								name: "Tanstack Router",
								render: <TanStackRouterDevtoolsPanel />,
							},
							TanStackQueryDevtools,
						]}
					/>
				)}
				<Scripts />
			</body>
		</html>
	);
}

function NotFound() {
	return (
		<div className="mx-auto w-full max-w-3xl p-4 md:p-6">
			<Empty>
				<EmptyHeader>
					<EmptyMedia variant="icon">
						<CompassIcon aria-hidden="true" />
					</EmptyMedia>
					<EmptyTitle>Page not found</EmptyTitle>
					<EmptyDescription>
						That page does not exist or was moved. Check the address or head
						back to the overview.
					</EmptyDescription>
				</EmptyHeader>
				<EmptyContent>
					<Button variant="outline" render={<Link to="/" />}>
						Back to overview
					</Button>
				</EmptyContent>
			</Empty>
		</div>
	);
}

function RoutePending() {
	return (
		<div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-4 md:p-6">
			<div className="flex flex-col gap-2">
				<Skeleton className="h-3 w-24" />
				<Skeleton className="h-8 w-72" />
				<Skeleton className="h-4 w-full max-w-xl" />
			</div>
			<div className="grid gap-4 md:grid-cols-3">
				<Skeleton className="h-28" />
				<Skeleton className="h-28" />
				<Skeleton className="h-28" />
			</div>
			<Skeleton className="h-64" />
		</div>
	);
}

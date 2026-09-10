import { TanStackDevtools } from "@tanstack/react-devtools";
import type { QueryClient } from "@tanstack/react-query";
import {
	createRootRouteWithContext,
	HeadContent,
	Link,
	Scripts,
} from "@tanstack/react-router";
import { TanStackRouterDevtoolsPanel } from "@tanstack/react-router-devtools";
import type { ReactNode } from "react";
import TanStackQueryDevtools from "../integrations/tanstack-query/devtools";
import appCss from "../styles.css?url";

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
		],
		links: [
			{
				rel: "stylesheet",
				href: appCss,
			},
		],
	}),
	shellComponent: RootDocument,
});

function RootDocument({ children }: { children: ReactNode }) {
	return (
		<html lang="en" className="dark">
			<head>
				<HeadContent />
			</head>
			<body className="flex min-h-dvh flex-col">
				<a
					href="#main"
					className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:rounded-full focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground"
				>
					Skip to content
				</a>
				<header className="sticky top-0 z-40 border-b border-border bg-background">
					<nav className="mx-auto flex w-full max-w-5xl items-center justify-between gap-6 px-6 py-3">
						<Link
							to="/"
							className="text-display-xs tracking-tight text-foreground no-underline"
						>
							TerraSentry
						</Link>
						<div className="flex items-center gap-6">
							<a
								href="#capabilities"
								className="text-body-sm text-muted-foreground no-underline transition-colors hover:text-foreground"
							>
								Capabilities
							</a>
							<a
								href="#runs"
								className="text-body-sm text-muted-foreground no-underline transition-colors hover:text-foreground"
							>
								Runs
							</a>
						</div>
					</nav>
				</header>
				<div id="main" className="flex-1">
					{children}
				</div>
				<footer className="border-t border-border">
					<div className="mx-auto flex w-full max-w-5xl flex-col gap-3 px-6 py-12">
						<p className="eyebrow-sm text-muted-foreground">TerraSentry</p>
						<p className="max-w-xl text-body-sm text-body-mid">
							Satellite and supply-chain evidence for EUDR due diligence,
							verified in code and cited end to end.
						</p>
					</div>
				</footer>
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

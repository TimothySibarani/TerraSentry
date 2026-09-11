import { Link, useRouterState } from "@tanstack/react-router";
import {
	ActivityIcon,
	Building2Icon,
	LayoutDashboardIcon,
	LayersIcon,
	SatelliteIcon,
} from "lucide-react";

import { ApiStatus } from "#/components/api-status";
import {
	Sidebar,
	SidebarContent,
	SidebarFooter,
	SidebarGroup,
	SidebarGroupContent,
	SidebarGroupLabel,
	SidebarHeader,
	SidebarMenu,
	SidebarMenuButton,
	SidebarMenuItem,
	SidebarRail,
} from "#/components/ui/sidebar";

const NAV_ITEMS = [
	{ to: "/", label: "Overview", icon: LayoutDashboardIcon },
	{ to: "/runs", label: "Runs", icon: ActivityIcon },
	{ to: "/batch", label: "Batch", icon: LayersIcon },
	{ to: "/suppliers", label: "Suppliers", icon: Building2Icon },
] as const;

export function AppSidebar() {
	const pathname = useRouterState({
		select: (state) => state.location.pathname,
	});

	return (
		<Sidebar collapsible="icon">
			<SidebarHeader>
				<SidebarMenu>
					<SidebarMenuItem>
						<SidebarMenuButton size="lg" render={<Link to="/" />}>
							<div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent-sunset/10 text-accent-sunset">
								<SatelliteIcon aria-hidden="true" />
							</div>
							<div className="grid flex-1 text-left leading-tight">
								<span className="truncate text-body-sm text-foreground">
									TerraSentry
								</span>
								<span className="truncate text-caption-mono-sm text-muted-foreground">
									EUDR cockpit
								</span>
							</div>
						</SidebarMenuButton>
					</SidebarMenuItem>
				</SidebarMenu>
			</SidebarHeader>
			<SidebarContent>
				<SidebarGroup>
					<SidebarGroupLabel>Operations</SidebarGroupLabel>
					<SidebarGroupContent>
						<SidebarMenu>
							{NAV_ITEMS.map((item) => {
								const active =
									item.to === "/"
										? pathname === "/"
										: pathname === item.to ||
											pathname.startsWith(`${item.to}/`);
								return (
									<SidebarMenuItem key={item.to}>
										<SidebarMenuButton
											tooltip={item.label}
											isActive={active}
											render={<Link to={item.to} />}
										>
											<item.icon aria-hidden="true" />
											<span>{item.label}</span>
										</SidebarMenuButton>
									</SidebarMenuItem>
								);
							})}
						</SidebarMenu>
					</SidebarGroupContent>
				</SidebarGroup>
			</SidebarContent>
			<SidebarFooter>
				<div className="flex items-center gap-2 px-2 py-1 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
					<ApiStatus />
				</div>
				<p className="px-2 pb-1 text-caption-mono-sm text-muted-foreground/70 group-data-[collapsible=icon]:hidden">
					Legality data is synthetic and labelled
				</p>
			</SidebarFooter>
			<SidebarRail />
		</Sidebar>
	);
}

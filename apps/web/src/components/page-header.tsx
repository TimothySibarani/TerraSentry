import type { ReactNode } from "react";

export function PageHeader({
	eyebrow,
	title,
	description,
	actions,
}: {
	eyebrow?: string;
	title: string;
	description?: ReactNode;
	actions?: ReactNode;
}) {
	return (
		<div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
			<div className="flex min-w-0 flex-col gap-1.5">
				{eyebrow && (
					<p className="eyebrow-sm text-muted-foreground">{eyebrow}</p>
				)}
				<h1 className="text-balance text-display-xs text-foreground md:text-display-sm">
					{title}
				</h1>
				{description && (
					<p className="max-w-2xl text-pretty text-body-sm text-muted-foreground">
						{description}
					</p>
				)}
			</div>
			{actions && (
				<div className="flex flex-wrap items-center gap-2">{actions}</div>
			)}
		</div>
	);
}

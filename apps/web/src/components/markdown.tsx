import type { ComponentProps } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "#/lib/utils";

export interface MarkdownProps {
	content: string;
	className?: string;
}

const remarkPlugins = [remarkGfm];

export function Markdown({ content, className }: MarkdownProps) {
	return (
		<div
			data-slot="markdown"
			className={cn("w-full text-body-sm text-foreground", className)}
		>
			<ReactMarkdown
				remarkPlugins={remarkPlugins}
				components={{
					h1: ({ className: headingClass, ...props }) => (
						<h1
							className={cn(
								"mt-6 mb-2 text-body-lg font-medium tracking-tight text-foreground first:mt-0",
								headingClass,
							)}
							{...props}
						/>
					),
					h2: ({ className: headingClass, ...props }) => (
						<h2
							className={cn(
								"mt-5 mb-2 border-b border-border/50 pb-1 text-body-md font-medium tracking-tight text-foreground first:mt-0",
								headingClass,
							)}
							{...props}
						/>
					),
					h3: ({ className: headingClass, ...props }) => (
						<h3
							className={cn(
								"mt-4 mb-1.5 text-body-sm font-medium tracking-tight text-foreground first:mt-0",
								headingClass,
							)}
							{...props}
						/>
					),
					h4: ({ className: headingClass, ...props }) => (
						<h4
							className={cn(
								"mt-3 mb-1 text-body-sm font-medium tracking-tight text-foreground first:mt-0",
								headingClass,
							)}
							{...props}
						/>
					),
					p: ({ className: pClass, ...props }) => (
						<p
							className={cn(
								"mb-3 text-body-sm leading-relaxed text-foreground/90 last:mb-0",
								pClass,
							)}
							{...props}
						/>
					),
					ul: ({ className: ulClass, ...props }) => (
						<ul
							className={cn(
								"mb-3 list-outside list-disc space-y-1 pl-4 text-body-sm text-foreground/90 last:mb-0",
								ulClass,
							)}
							{...props}
						/>
					),
					ol: ({ className: olClass, ...props }) => (
						<ol
							className={cn(
								"mb-3 list-outside list-decimal space-y-1 pl-4 text-body-sm text-foreground/90 last:mb-0",
								olClass,
							)}
							{...props}
						/>
					),
					li: ({ className: liClass, ...props }) => (
						<li
							className={cn(
								"text-body-sm leading-relaxed text-foreground/90",
								liClass,
							)}
							{...props}
						/>
					),
					strong: ({ className: strongClass, ...props }) => (
						<strong
							className={cn("font-medium text-foreground", strongClass)}
							{...props}
						/>
					),
					em: ({ className: emClass, ...props }) => (
						<em
							className={cn("italic text-foreground/90", emClass)}
							{...props}
						/>
					),
					blockquote: ({ className: quoteClass, ...props }) => (
						<blockquote
							className={cn(
								"my-2 border-l-2 border-border pl-3 text-body-sm italic text-muted-foreground",
								quoteClass,
							)}
							{...props}
						/>
					),
					hr: ({ className: hrClass, ...props }) => (
						<hr
							className={cn("my-4 border-t border-border", hrClass)}
							{...props}
						/>
					),
					a: ({ className: aClass, ...props }) => (
						<a
							className={cn(
								"text-primary underline underline-offset-4 transition-colors hover:text-primary/80",
								aClass,
							)}
							target="_blank"
							rel="noreferrer"
							{...props}
						/>
					),
					code: ({
						className: codeClass,
						children,
						...props
					}: ComponentProps<"code">) => (
						<code
							className={cn(
								"rounded border border-border/60 bg-muted/80 px-1.5 py-0.5 font-mono text-[0.8125rem] text-foreground align-baseline",
								codeClass,
							)}
							{...props}
						>
							{children}
						</code>
					),
					pre: ({ className: preClass, ...props }) => (
						<pre
							className={cn(
								"my-2 overflow-x-auto rounded-md border border-border bg-muted/50 p-3 font-mono text-xs text-foreground [&>code]:inline [&>code]:border-0 [&>code]:bg-transparent [&>code]:p-0",
								preClass,
							)}
							{...props}
						/>
					),
					table: ({ className: tableClass, ...props }) => (
						<div className="my-3 w-full overflow-x-auto rounded-md border border-border">
							<table
								className={cn(
									"w-full caption-bottom text-left text-xs",
									tableClass,
								)}
								{...props}
							/>
						</div>
					),
					thead: ({ className: theadClass, ...props }) => (
						<thead
							className={cn(
								"border-b border-border bg-muted/40 font-medium text-muted-foreground [&_tr]:border-b",
								theadClass,
							)}
							{...props}
						/>
					),
					tbody: ({ className: tbodyClass, ...props }) => (
						<tbody
							className={cn(
								"divide-y divide-border [&_tr:last-child]:border-0",
								tbodyClass,
							)}
							{...props}
						/>
					),
					tr: ({ className: trClass, ...props }) => (
						<tr
							className={cn(
								"border-b border-border/50 transition-colors hover:bg-muted/20",
								trClass,
							)}
							{...props}
						/>
					),
					th: ({ className: thClass, ...props }) => (
						<th
							className={cn(
								"h-8 px-3 py-1.5 text-left align-middle font-medium whitespace-nowrap text-muted-foreground",
								thClass,
							)}
							{...props}
						/>
					),
					td: ({ className: tdClass, ...props }) => (
						<td
							className={cn(
								"px-3 py-2 align-top text-body-sm text-foreground/90",
								tdClass,
							)}
							{...props}
						/>
					),
				}}
			>
				{content}
			</ReactMarkdown>
		</div>
	);
}

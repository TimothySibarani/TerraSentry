import { AlertDialog as AlertDialogPrimitive } from "@base-ui/react/alert-dialog";
import type * as React from "react";

import { Button } from "#/components/ui/button";
import { cn } from "#/lib/utils";

function AlertDialog({ ...props }: AlertDialogPrimitive.Root.Props) {
	return <AlertDialogPrimitive.Root data-slot="alert-dialog" {...props} />;
}

function AlertDialogTrigger({ ...props }: AlertDialogPrimitive.Trigger.Props) {
	return (
		<AlertDialogPrimitive.Trigger data-slot="alert-dialog-trigger" {...props} />
	);
}

function AlertDialogPortal({ ...props }: AlertDialogPrimitive.Portal.Props) {
	return (
		<AlertDialogPrimitive.Portal data-slot="alert-dialog-portal" {...props} />
	);
}

function AlertDialogOverlay({
	className,
	...props
}: AlertDialogPrimitive.Backdrop.Props) {
	return (
		<AlertDialogPrimitive.Backdrop
			data-slot="alert-dialog-overlay"
			className={cn(
				"fixed inset-0 isolate z-50 bg-black/80 duration-100 supports-backdrop-filter:backdrop-blur-xs data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0",
				className,
			)}
			{...props}
		/>
	);
}

function AlertDialogContent({
	className,
	size = "default",
	...props
}: AlertDialogPrimitive.Popup.Props & {
	size?: "default" | "sm";
}) {
	return (
		<AlertDialogPortal>
			<AlertDialogOverlay />
			<AlertDialogPrimitive.Popup
				data-slot="alert-dialog-content"
				data-size={size}
				className={cn(
					"group/alert-dialog-content fixed top-1/2 left-1/2 z-50 grid w-full -translate-x-1/2 -translate-y-1/2 gap-3 rounded-xl bg-popover p-4 text-popover-foreground ring-1 ring-foreground/10 duration-100 outline-none data-[size=default]:max-w-xs data-[size=sm]:max-w-64 data-[size=default]:sm:max-w-md data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
					className,
				)}
				{...props}
			/>
		</AlertDialogPortal>
	);
}

function AlertDialogHeader({
	className,
	...props
}: React.ComponentProps<"div">) {
	return (
		<div
			data-slot="alert-dialog-header"
			className={cn("flex flex-col gap-1 text-left", className)}
			{...props}
		/>
	);
}

function AlertDialogFooter({
	className,
	...props
}: React.ComponentProps<"div">) {
	return (
		<div
			data-slot="alert-dialog-footer"
			className={cn(
				"flex flex-col-reverse gap-2 sm:flex-row sm:justify-end",
				className,
			)}
			{...props}
		/>
	);
}

function AlertDialogTitle({
	className,
	...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Title>) {
	return (
		<AlertDialogPrimitive.Title
			data-slot="alert-dialog-title"
			className={cn("text-sm font-medium", className)}
			{...props}
		/>
	);
}

function AlertDialogDescription({
	className,
	...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Description>) {
	return (
		<AlertDialogPrimitive.Description
			data-slot="alert-dialog-description"
			className={cn(
				"text-xs/relaxed text-balance text-muted-foreground md:text-pretty",
				className,
			)}
			{...props}
		/>
	);
}

function AlertDialogAction({
	className,
	...props
}: React.ComponentProps<typeof Button>) {
	return (
		<Button
			data-slot="alert-dialog-action"
			className={cn(className)}
			{...props}
		/>
	);
}

function AlertDialogCancel({
	className,
	variant = "outline",
	size = "default",
	...props
}: AlertDialogPrimitive.Close.Props &
	Pick<React.ComponentProps<typeof Button>, "variant" | "size">) {
	return (
		<AlertDialogPrimitive.Close
			data-slot="alert-dialog-cancel"
			className={cn(className)}
			render={<Button variant={variant} size={size} />}
			{...props}
		/>
	);
}

export {
	AlertDialog,
	AlertDialogAction,
	AlertDialogCancel,
	AlertDialogContent,
	AlertDialogDescription,
	AlertDialogFooter,
	AlertDialogHeader,
	AlertDialogOverlay,
	AlertDialogPortal,
	AlertDialogTitle,
	AlertDialogTrigger,
};

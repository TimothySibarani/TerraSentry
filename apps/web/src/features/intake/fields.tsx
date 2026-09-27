import type { ReactNode } from "react";

import {
	Field,
	FieldDescription,
	FieldError,
	FieldLabel,
} from "#/components/ui/field";
import { Input } from "#/components/ui/input";

/** Field ids are the server's dotted paths, so 422 issues land on the right input. */
export function fieldId(field: string): string {
	return `intake-${field.replace(/\./g, "-")}`;
}

export function TextField({
	field,
	label,
	value,
	onChange,
	error,
	description,
	required = false,
	placeholder,
	inputMode,
	className,
	autoComplete = "off",
	suffix,
}: {
	field: string;
	label: string;
	value: string;
	onChange: (value: string) => void;
	error?: string;
	description?: ReactNode;
	required?: boolean;
	placeholder?: string;
	inputMode?: "text" | "decimal" | "numeric";
	className?: string;
	autoComplete?: string;
	suffix?: string;
}) {
	const id = fieldId(field);
	const describedBy = [
		description ? `${id}-description` : null,
		error ? `${id}-error` : null,
	]
		.filter(Boolean)
		.join(" ");
	return (
		<Field data-invalid={error ? true : undefined} className={className}>
			<FieldLabel htmlFor={id}>
				{label}
				{required && (
					<span aria-hidden="true" className="text-muted-foreground">
						*
					</span>
				)}
			</FieldLabel>
			<div className="relative">
				<Input
					id={id}
					value={value}
					onChange={(event) => onChange(event.target.value)}
					aria-invalid={error ? true : undefined}
					aria-required={required || undefined}
					aria-describedby={describedBy || undefined}
					placeholder={placeholder}
					inputMode={inputMode}
					autoComplete={autoComplete}
					className={suffix ? "pr-10" : undefined}
				/>
				{suffix && (
					<span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-caption-mono-sm text-muted-foreground">
						{suffix}
					</span>
				)}
			</div>
			{description && (
				<FieldDescription id={`${id}-description`}>
					{description}
				</FieldDescription>
			)}
			{error && <FieldError id={`${id}-error`}>{error}</FieldError>}
		</Field>
	);
}

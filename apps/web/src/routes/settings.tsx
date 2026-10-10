import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import {
	ApiClientError,
	type OperatorSettingOut,
	type OperatorUpdate,
} from "@terrasentry/api-client";
import { useState } from "react";
import { ErrorState } from "#/components/error-state";
import { PageHeader } from "#/components/page-header";
import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "#/components/ui/card";
import { Field, FieldLabel } from "#/components/ui/field";
import { healthQuery } from "#/features/health/queries";
import { TextField } from "#/features/intake/fields";
import { operatorQuery, useSaveOperator } from "#/features/settings/queries";

export const Route = createFileRoute("/settings")({ component: SettingsPage });

const fields = [
	["legal_name", "Legal name"],
	["identifier_value", "EORI"],
	["address_line", "Street address"],
	["postal_code", "Postal code"],
	["city", "City"],
	["country", "Address country (ISO code)"],
	["email", "Email"],
	["phone", "Phone"],
	["country_of_activity", "Activity country (ISO code)"],
	["border_cross_country", "Border country (ISO code)"],
] as const;

function editable(profile: OperatorSettingOut["profile"]): OperatorUpdate {
	return {
		legal_name: profile.legal_name,
		identifier_type: "eori",
		identifier_value: profile.identifier_value,
		address_line: profile.address_line,
		postal_code: profile.postal_code,
		city: profile.city,
		country: profile.country,
		email: profile.email,
		phone: profile.phone,
		activity_type: profile.activity_type,
		country_of_activity: profile.country_of_activity,
		border_cross_country: profile.border_cross_country,
	};
}

export function OperatorForm({ initial }: { initial: OperatorSettingOut }) {
	const [form, setForm] = useState(() => editable(initial.profile));
	const save = useSaveOperator();
	const errors =
		save.error instanceof ApiClientError
			? Object.fromEntries(
					(save.error.issues ?? []).map((issue) => [
						issue.field,
						issue.message,
					]),
				)
			: {};
	return (
		<form
			className="flex flex-col gap-5"
			onSubmit={(event) => {
				event.preventDefault();
				save.mutate(form, {
					onSuccess: (saved) => setForm(editable(saved.profile)),
				});
			}}
		>
			<p className="text-body-sm text-muted-foreground">
				{initial.configured
					? "Configured by the operator."
					: "Synthetic demo profile in use. Saving replaces it for future runs."}{" "}
				EORI format is checked; registration is not verified. Accepted runs keep
				their original profile.
			</p>
			<div className="grid gap-4 md:grid-cols-2">
				{fields.map(([name, label]) => (
					<TextField
						key={name}
						field={name}
						label={label}
						required
						type={name === "email" ? "email" : "text"}
						value={form[name]}
						onChange={(value) => {
							save.reset();
							setForm((current) => ({ ...current, [name]: value }));
						}}
						error={errors[name]}
					/>
				))}
			</div>
			<Field>
				<FieldLabel htmlFor="operator-activity">Activity</FieldLabel>
				<select
					id="operator-activity"
					aria-label="Activity"
					className="rounded-md border border-input bg-background p-2 text-foreground"
					value={form.activity_type}
					onChange={(event) => {
						save.reset();
						const activity_type = event.target.value;
						if (
							activity_type === "IMPORT" ||
							activity_type === "EXPORT" ||
							activity_type === "DOMESTIC"
						)
							setForm((current) => ({ ...current, activity_type }));
					}}
				>
					<option value="IMPORT">Import</option>
					<option value="EXPORT">Export</option>
					<option value="DOMESTIC">Domestic</option>
				</select>
			</Field>
			{save.isError && (
				<p role="alert" className="text-body-sm text-status-risk">
					{Object.keys(errors).length
						? "Correct the highlighted fields."
						: "Could not save the operator profile."}
				</p>
			)}
			{save.isSuccess && (
				<output className="text-body-sm text-status-compliant">
					Operator profile saved.
				</output>
			)}
			<Button type="submit" disabled={save.isPending}>
				{save.isPending ? "Saving…" : "Save operator profile"}
			</Button>
		</form>
	);
}

function SettingsPage() {
	const operator = useQuery(operatorQuery());
	const health = useQuery(healthQuery());
	return (
		<div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
			<PageHeader
				title="Settings"
				description="Operator details used in future due diligence statements."
			/>
			<Card>
				<CardHeader>
					<CardTitle>Operator profile</CardTitle>
				</CardHeader>
				<CardContent>
					{operator.isError ? (
						<ErrorState
							error={operator.error}
							onRetry={() => void operator.refetch()}
						/>
					) : operator.data ? (
						<OperatorForm initial={operator.data} />
					) : (
						<output>Loading operator profile…</output>
					)}
				</CardContent>
			</Card>
			<Card>
				<CardHeader>
					<CardTitle>Integrations</CardTitle>
				</CardHeader>
				<CardContent className="flex flex-wrap gap-3">
					<Badge variant="outline">
						GFW: {health.data?.gfwConfigured ? "configured" : "unconfigured"}
					</Badge>
					<Badge variant="outline">
						FIRMS:{" "}
						{health.data?.firmsConfigured ? "configured" : "unconfigured"}
					</Badge>
					<Badge variant="outline">
						Bedrock:{" "}
						{health.data?.bedrockConfigured ? "configured" : "unconfigured"}
					</Badge>
					<Badge variant="outline">
						SAP AI Core:{" "}
						{health.data?.aicoreConfigured ? "configured" : "unconfigured"}
					</Badge>
					<Badge variant="outline">
						Default model: {health.data?.defaultModel ?? "unknown"}
					</Badge>
					<Badge variant="outline">
						SAP: {health.data?.sapMode ?? "unknown"}
					</Badge>
					<p className="w-full text-body-sm text-muted-foreground">
						Credentials are configured on the server. Rubric 1.1 evaluates the
						evidence. External decision engine and TRACES submission are not
						implemented.
					</p>
				</CardContent>
			</Card>
		</div>
	);
}

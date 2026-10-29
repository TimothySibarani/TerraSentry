import { InfoIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "#/components/ui/alert";
import { Button } from "#/components/ui/button";
import {
	Field,
	FieldContent,
	FieldDescription,
	FieldGroup,
	FieldLabel,
	FieldLegend,
	FieldSet,
	FieldTitle,
} from "#/components/ui/field";
import { RadioGroup, RadioGroupItem } from "#/components/ui/radio-group";
import {
	Select,
	SelectContent,
	SelectGroup,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "#/components/ui/select";
import { Textarea } from "#/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "#/components/ui/toggle-group";
import { fieldId, TextField } from "#/features/intake/fields";
import {
	CERTIFICATIONS,
	COMMODITIES,
	type FieldErrors,
	type IntakeForm,
	PERMIT_TYPES,
	WOOD_LOTS,
} from "#/features/intake/form";

interface StepProps {
	form: IntakeForm;
	update: (patch: Partial<IntakeForm>) => void;
	errors: FieldErrors;
}

export function SupplierStep({ form, update, errors }: StepProps) {
	return (
		<FieldGroup>
			<div className="grid gap-4 md:grid-cols-2">
				<TextField
					field="supplier.legal_name"
					label="Legal name"
					required
					placeholder="PT Sawit Makmur Lestari"
					value={form.legalName}
					onChange={(legalName) => update({ legalName })}
					error={errors["supplier.legal_name"]}
					description="As registered; it becomes the producer name on the DDS."
				/>
				<TextField
					field="supplier.trading_name"
					label="Trading name"
					placeholder="Sawit Makmur"
					value={form.tradingName}
					onChange={(tradingName) => update({ tradingName })}
				/>
				<TextField
					field="supplier.group"
					label="Corporate group"
					placeholder="Optional"
					value={form.group}
					onChange={(group) => update({ group })}
				/>
				<div className="grid gap-4 sm:grid-cols-2">
					<TextField
						field="supplier.nib"
						label="NIB"
						inputMode="numeric"
						placeholder="13 digits"
						value={form.nib}
						onChange={(nib) => update({ nib })}
						description="Business registration number."
					/>
					<TextField
						field="supplier.npwp"
						label="NPWP"
						placeholder="00.000.000.0-000.000"
						value={form.npwp}
						onChange={(npwp) => update({ npwp })}
						description="Tax id."
					/>
				</div>
			</div>
			<FieldSet>
				<FieldLegend variant="label">Sustainability certifications</FieldLegend>
				<FieldDescription>
					A certification is mitigating evidence in the rubric; it never
					overrides a satellite or legality flag.
				</FieldDescription>
				<ToggleGroup
					aria-label="Certifications held"
					variant="outline"
					multiple
					value={[...form.certifications]}
					onValueChange={(values) =>
						update({ certifications: values as Array<string> })
					}
					className="flex-wrap"
				>
					{CERTIFICATIONS.map((certification) => (
						<ToggleGroupItem key={certification} value={certification}>
							{certification}
						</ToggleGroupItem>
					))}
				</ToggleGroup>
			</FieldSet>
			<Field>
				<FieldLabel htmlFor={fieldId("supplier.beneficial_owners")}>
					Beneficial owners
				</FieldLabel>
				<Textarea
					id={fieldId("supplier.beneficial_owners")}
					value={form.owners}
					placeholder="One name per line"
					onChange={(event) => update({ owners: event.target.value })}
				/>
			</Field>
		</FieldGroup>
	);
}

const PERMIT_STATUS_ITEMS = {
	active: "Active",
	expired: "Expired",
	suspended: "Suspended",
} as const;

export function LegalityStep({ form, update, errors }: StepProps) {
	return (
		<FieldGroup>
			<Alert>
				<InfoIcon aria-hidden="true" />
				<AlertTitle>Declared, not registry-verified</AlertTitle>
				<AlertDescription>
					Indonesia has no public HGU/PBPH registry API. TerraSentry scores the
					permit you declare and labels it as supplier-declared on every
					evidence row and in the DDS.
				</AlertDescription>
			</Alert>
			<FieldSet>
				<FieldLegend variant="label">Permit type (Indonesia)</FieldLegend>
				<RadioGroup
					value={form.permitType}
					onValueChange={(value) =>
						update({ permitType: value as IntakeForm["permitType"] })
					}
					className="grid gap-3 md:grid-cols-3"
				>
					{PERMIT_TYPES.map((permit) => (
						<FieldLabel key={permit.value} htmlFor={`permit-${permit.value}`}>
							<Field orientation="horizontal">
								<RadioGroupItem
									value={permit.value}
									id={`permit-${permit.value}`}
								/>
								<FieldContent>
									<FieldTitle>{permit.label}</FieldTitle>
									<FieldDescription>{permit.description}</FieldDescription>
								</FieldContent>
							</Field>
						</FieldLabel>
					))}
				</RadioGroup>
			</FieldSet>
			<div className="grid gap-4 md:grid-cols-2">
				<TextField
					field="legality.permit_expiry"
					label="Permit expiry"
					type="date"
					value={form.permitExpiry}
					onChange={(permitExpiry) => update({ permitExpiry })}
					error={errors["legality.permit_expiry"]}
					description="Optional. Expiry before the assessment date is a critical flag; unknown expiry is disclosed."
				/>
				<TextField
					field="legality.declared_holder"
					label="Declared permit holder"
					value={form.declaredHolder}
					onChange={(declaredHolder) => update({ declaredHolder })}
					error={errors["legality.declared_holder"]}
					placeholder={form.legalName || "Defaults to supplier legal name"}
				/>
			</div>
			{form.permitType !== "none" && (
				<div className="grid gap-4 md:grid-cols-3">
					<TextField
						field="legality.permit_number"
						label={`${form.permitType.toUpperCase()} number`}
						required
						placeholder={
							form.permitType === "hgu"
								? "12/HGU/BPN/2019"
								: "SK.123/Menlhk/2020"
						}
						value={form.permitNumber}
						onChange={(permitNumber) => update({ permitNumber })}
						error={errors["legality.permit_number"]}
					/>
					<Field>
						<FieldLabel htmlFor="intake-legality-permit_status">
							Permit status
						</FieldLabel>
						<Select
							items={PERMIT_STATUS_ITEMS}
							value={form.permitStatus}
							onValueChange={(value) =>
								update({ permitStatus: value as IntakeForm["permitStatus"] })
							}
						>
							<SelectTrigger
								id="intake-legality-permit_status"
								className="w-full"
							>
								<SelectValue />
							</SelectTrigger>
							<SelectContent>
								<SelectGroup>
									{Object.entries(PERMIT_STATUS_ITEMS).map(([value, label]) => (
										<SelectItem key={value} value={value}>
											{label}
										</SelectItem>
									))}
								</SelectGroup>
							</SelectContent>
						</Select>
						<FieldDescription>
							Expired or suspended is a critical legality flag.
						</FieldDescription>
					</Field>
					<TextField
						field="legality.concession_area_ha"
						label="Concession area"
						inputMode="decimal"
						suffix="ha"
						placeholder="Defaults to the plot area"
						value={form.concessionAreaHa}
						onChange={(concessionAreaHa) => update({ concessionAreaHa })}
						error={errors["legality.concession_area_ha"]}
						description="A concession smaller than the plot is an area mismatch."
					/>
				</div>
			)}
		</FieldGroup>
	);
}

export function ConsignmentStep({ form, update, errors }: StepProps) {
	const selected = COMMODITIES.find((item) => item.value === form.commodity);
	return (
		<FieldGroup>
			<FieldSet>
				<FieldLegend variant="label">Commodity (EUDR Annex I)</FieldLegend>
				<ToggleGroup
					aria-label="Commodity"
					variant="outline"
					value={[form.commodity]}
					onValueChange={(values) => {
						const next = COMMODITIES.find((item) => item.value === values[0]);
						if (next) {
							// Only replace defaults, never text the user typed.
							const previous = COMMODITIES.find(
								(item) => item.value === form.commodity,
							);
							const keep = (current: string, old?: string) =>
								current && current !== old ? current : undefined;
							update({
								commodity: next.value,
								description:
									keep(form.description, previous?.description) ??
									next.description,
								speciesScientific:
									keep(form.speciesScientific, previous?.scientific) ??
									next.scientific,
								speciesCommon:
									keep(form.speciesCommon, previous?.common) ?? next.common,
							});
						}
					}}
					className="flex-wrap"
				>
					{COMMODITIES.map((commodity) => (
						<ToggleGroupItem key={commodity.value} value={commodity.value}>
							{commodity.label}
						</ToggleGroupItem>
					))}
				</ToggleGroup>
				{form.commodity === "wood" && (
					<div className="flex flex-wrap items-center gap-2">
						<span className="text-caption-mono-sm text-muted-foreground">
							Typical lots
						</span>
						{WOOD_LOTS.map((lot) => (
							<Button
								key={lot.hs}
								type="button"
								size="xs"
								variant={form.hsHeading === lot.hs ? "secondary" : "outline"}
								aria-pressed={form.hsHeading === lot.hs}
								onClick={() =>
									update({ description: lot.description, hsHeading: lot.hs })
								}
							>
								{lot.label} · HS {lot.hs}
							</Button>
						))}
					</div>
				)}
			</FieldSet>
			<div className="grid gap-4 md:grid-cols-2">
				<TextField
					field="consignment.description"
					label="Description of goods"
					required
					value={form.description}
					onChange={(description) => update({ description })}
					error={errors["consignment.description"]}
				/>
				<TextField
					field="consignment.hs_heading"
					label="HS heading"
					inputMode="numeric"
					placeholder={selected ? `${selected.hs} (default)` : ""}
					value={form.hsHeading}
					onChange={(hsHeading) => update({ hsHeading })}
					error={errors["consignment.hs_heading"]}
					description="Leave empty to use the commodity's default heading."
				/>
				<TextField
					field="consignment.species_scientific"
					label="Species (scientific)"
					placeholder={form.commodity === "wood" ? "e.g. Acacia mangium" : ""}
					value={form.speciesScientific}
					onChange={(speciesScientific) => update({ speciesScientific })}
				/>
				<TextField
					field="consignment.species_common"
					label="Species (common)"
					value={form.speciesCommon}
					onChange={(speciesCommon) => update({ speciesCommon })}
				/>
				<TextField
					field="consignment.net_weight_kg"
					label="Net weight"
					required
					inputMode="decimal"
					suffix="kg"
					placeholder="25000"
					value={form.netWeightKg}
					onChange={(netWeightKg) => update({ netWeightKg })}
					error={errors["consignment.net_weight_kg"]}
				/>
				<TextField
					field="consignment.harvest_year"
					label="Harvest year"
					required
					inputMode="numeric"
					value={form.harvestYear}
					onChange={(harvestYear) => update({ harvestYear })}
					error={errors["consignment.harvest_year"]}
				/>
			</div>
		</FieldGroup>
	);
}

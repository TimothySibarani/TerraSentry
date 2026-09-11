import { useState } from "react";

import { ErrorState } from "#/components/error-state";
import { Button } from "#/components/ui/button";
import {
	Dialog,
	DialogClose,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
	DialogTrigger,
} from "#/components/ui/dialog";
import {
	Field,
	FieldDescription,
	FieldGroup,
	FieldLabel,
} from "#/components/ui/field";
import { Input } from "#/components/ui/input";
import {
	Select,
	SelectContent,
	SelectGroup,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "#/components/ui/select";
import { Spinner } from "#/components/ui/spinner";
import { Textarea } from "#/components/ui/textarea";
import { useRunDecision } from "#/features/runs/mutations";

const DECISION_ITEMS = {
	approve: "Approve — keep the ambiguous verdict",
	override: "Override — record a different human call",
} as const;

export function ReviewDialog({ runId }: { runId: string }) {
	const [open, setOpen] = useState(false);
	const [decision, setDecision] = useState<"approve" | "override">("approve");
	const [reviewer, setReviewer] = useState("demo-reviewer");
	const [note, setNote] = useState("");
	const mutation = useRunDecision(runId);

	const submit = async () => {
		try {
			await mutation.mutateAsync({
				decision,
				reviewer: reviewer.trim() || "human",
				note: note.trim(),
			});
			setOpen(false);
			setNote("");
		} catch {
			// ErrorState renders the typed API failure.
		}
	};

	return (
		<Dialog open={open} onOpenChange={setOpen}>
			<DialogTrigger render={<Button />}>Record decision</DialogTrigger>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>Human review decision</DialogTitle>
					<DialogDescription>
						The ambiguous verdict stays on the record. Approving releases the
						withheld DDS; overriding records your call alongside the original
						assessment.
					</DialogDescription>
				</DialogHeader>
				<form
					className="flex flex-col gap-4"
					onSubmit={(event) => {
						event.preventDefault();
						void submit();
					}}
				>
					<FieldGroup>
						<Field>
							<FieldLabel htmlFor="decision">Decision</FieldLabel>
							<Select
								items={DECISION_ITEMS}
								value={decision}
								onValueChange={(value) =>
									setDecision(value as "approve" | "override")
								}
							>
								<SelectTrigger id="decision" className="w-full">
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectGroup>
										<SelectItem value="approve">Approve</SelectItem>
										<SelectItem value="override">Override</SelectItem>
									</SelectGroup>
								</SelectContent>
							</Select>
							<FieldDescription>
								{decision === "approve"
									? "Releases the DDS with the original ambiguous verdict."
									: "Releases the DDS and records that a human overrode the rubric."}
							</FieldDescription>
						</Field>
						<Field>
							<FieldLabel htmlFor="reviewer">Reviewer</FieldLabel>
							<Input
								id="reviewer"
								name="reviewer"
								autoComplete="off"
								value={reviewer}
								onChange={(event) => setReviewer(event.target.value)}
							/>
						</Field>
						<Field>
							<FieldLabel htmlFor="note">Note</FieldLabel>
							<Textarea
								id="note"
								name="note"
								rows={3}
								placeholder="Checked the permit gap with the operator…"
								value={note}
								onChange={(event) => setNote(event.target.value)}
							/>
						</Field>
					</FieldGroup>
					{mutation.error && <ErrorState error={mutation.error} />}
					<DialogFooter>
						<DialogClose render={<Button variant="outline" type="button" />}>
							Cancel
						</DialogClose>
						<Button type="submit" disabled={mutation.isPending}>
							{mutation.isPending && (
								<Spinner
									aria-label="Recording decision"
									data-icon="inline-start"
								/>
							)}
							Record decision
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}

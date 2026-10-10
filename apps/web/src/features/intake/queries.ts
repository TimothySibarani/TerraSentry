import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiClientError, type RecordOut } from "@terrasentry/api-client";
import { useEffect, useRef, useState } from "react";
import type { IntakeForm } from "#/features/intake/form";
import { toSubmission } from "#/features/intake/form";
import type { PlotGeometry } from "#/features/intake/geometry";
import { runApi } from "#/lib/api";

function useDebounced<T>(value: T, delayMs: number): T {
	const [debounced, setDebounced] = useState(value);
	useEffect(() => {
		const timer = setTimeout(() => setDebounced(value), delayMs);
		return () => clearTimeout(timer);
	}, [value, delayMs]);
	return debounced;
}

/**
 * Server-measured geometry (geodesic area, centroid, validity). The server is
 * the authority for the EUDR 4 ha rule, so the form shows its answer, not a
 * client estimate.
 */
export function useGeometryCheck(
	geometry: PlotGeometry | null,
	declaredAreaHa: number | null,
) {
	const immediateKey = geometry
		? JSON.stringify([geometry, declaredAreaHa])
		: null;
	const key = useDebounced(immediateKey, 350);
	const query = useQuery({
		queryKey: ["intake", "geometry", key],
		enabled: key !== null,
		retry: false,
		staleTime: Number.POSITIVE_INFINITY,
		queryFn: () => {
			const [parsed, area] = JSON.parse(key ?? "[]") as [
				Record<string, unknown>,
				number | null,
			];
			return runApi((api) =>
				api.validateGeometry({ geometry: parsed, declared_area_ha: area }),
			);
		},
	});
	const current = immediateKey !== null && immediateKey === key;
	return {
		...query,
		data: current ? query.data : undefined,
		error: current ? query.error : null,
		isFetching: immediateKey !== null && (!current || query.isFetching),
		isCurrentValid: current && query.isSuccess,
	};
}

export function geometryIssue(error: unknown): string | null {
	if (error instanceof ApiClientError && error.status === 422) {
		return error.issues?.[0]?.message ?? "The server rejected this geometry.";
	}
	return error ? "Could not reach the API to measure the plot." : null;
}

/** Register the plot, then start the agent run on it. */
export function useScreenPlot() {
	const queryClient = useQueryClient();
	const registered = useRef<{ key: string; record: RecordOut } | null>(null);
	return useMutation({
		mutationFn: async ({
			form,
			model,
		}: {
			form: IntakeForm;
			model: "scripted" | "bedrock";
		}) => {
			const submission = toSubmission(form);
			const key = JSON.stringify(submission);
			if (registered.current?.key !== key) {
				registered.current = null;
				const record = await runApi((api) => api.createRecord(submission));
				registered.current = { key, record };
				void queryClient.invalidateQueries({ queryKey: ["records"] });
				void queryClient.invalidateQueries({ queryKey: ["suppliers"] });
			}
			const record = registered.current.record;
			const run = await runApi((api) =>
				api.createRun({ record_id: record.record_id, model }),
			);
			return { record, run };
		},
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: ["runs"] });
			void queryClient.invalidateQueries({ queryKey: ["records"] });
			void queryClient.invalidateQueries({ queryKey: ["suppliers"] });
		},
	});
}

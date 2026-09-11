import { queryOptions } from "@tanstack/react-query";

import { isTerminalState } from "#/features/runs/stream";
import { runApi } from "#/lib/api";

export function runsQuery() {
	return queryOptions({
		queryKey: ["runs"],
		queryFn: () => runApi((api) => api.listRuns()),
		staleTime: 5_000,
	});
}

export function runQuery(runId: string) {
	return queryOptions({
		queryKey: ["runs", runId],
		queryFn: () => runApi((api) => api.getRun(runId)),
		staleTime: 5_000,
	});
}

export function runEvidenceQuery(runId: string) {
	return queryOptions({
		queryKey: ["runs", runId, "evidence"],
		queryFn: () => runApi((api) => api.getRunEvidence(runId)),
		staleTime: 30_000,
	});
}

export function runDdsQuery(runId: string, enabled = true) {
	return queryOptions({
		queryKey: ["runs", runId, "dds"],
		queryFn: () => runApi((api) => api.getRunDds(runId)),
		enabled,
		staleTime: Number.POSITIVE_INFINITY,
	});
}

export function runDdsXmlQuery(runId: string, enabled = true) {
	return queryOptions({
		queryKey: ["runs", runId, "dds", "xml"],
		queryFn: () => runApi((api) => api.getRunDdsXml(runId)),
		enabled,
		staleTime: Number.POSITIVE_INFINITY,
	});
}

export function batchRunsQuery() {
	return queryOptions({
		queryKey: ["batch"],
		queryFn: () => runApi((api) => api.listBatchRuns()),
		staleTime: 5_000,
	});
}

export function batchRunQuery(batchRunId: string) {
	return queryOptions({
		queryKey: ["batch", batchRunId],
		queryFn: () => runApi((api) => api.getBatchRun(batchRunId)),
		staleTime: 5_000,
	});
}

export function batchRecordsQuery(batchRunId: string) {
	return queryOptions({
		queryKey: ["batch", batchRunId, "records"],
		queryFn: () => runApi((api) => api.getBatchRunRecords(batchRunId)),
		refetchInterval: (query) => {
			const records = query.state.data;
			if (!records || records.length === 0) {
				return false;
			}
			return records.some((record) => !isTerminalState(record.state))
				? 2_000
				: false;
		},
	});
}

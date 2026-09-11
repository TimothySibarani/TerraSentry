import { queryOptions } from "@tanstack/react-query";

import { runApi } from "#/lib/api";

export function suppliersQuery() {
	return queryOptions({
		queryKey: ["suppliers"],
		queryFn: () => runApi((api) => api.listSuppliers()),
		staleTime: 60_000,
	});
}

export function supplierQuery(supplierId: string) {
	return queryOptions({
		queryKey: ["suppliers", supplierId],
		queryFn: () => runApi((api) => api.getSupplier(supplierId)),
		staleTime: 60_000,
	});
}

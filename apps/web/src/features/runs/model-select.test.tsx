import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { useDefaultModel } from "./model-select";

const query = vi.hoisted(() => vi.fn());
vi.mock("#/features/health/queries", () => ({
	healthQuery: () => ({ queryKey: ["health"], queryFn: query }),
}));
afterEach(cleanup);
it("honors a scripted default even with Bedrock configured", async () => {
	query.mockResolvedValue({
		bedrockConfigured: true,
		defaultModel: "scripted",
	});
	const client = new QueryClient();
	const wrapper = ({ children }: { children: ReactNode }) => (
		<QueryClientProvider client={client}>{children}</QueryClientProvider>
	);
	const { result } = renderHook(() => useDefaultModel(), { wrapper });
	await waitFor(() => expect(client.getQueryData(["health"])).toBeDefined());
	expect(result.current).toBe("scripted");
});

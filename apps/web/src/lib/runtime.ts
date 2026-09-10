import { createApiRuntime } from "@terrasentry/api-client";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export const apiRuntime = createApiRuntime(baseUrl);

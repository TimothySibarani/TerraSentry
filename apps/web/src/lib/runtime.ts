import { createApiRuntime } from "@terrasentry/api-client";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
// ponytail: a VITE_ value ships in the browser bundle, so this is a shared
// demo token, not a secret. It only protects the API when the cockpit itself
// is access-controlled; per-user auth is the upgrade path.
const token = import.meta.env.VITE_API_TOKEN || undefined;

export const apiRuntime = createApiRuntime(baseUrl, token);

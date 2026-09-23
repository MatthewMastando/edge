import createClient from "openapi-fetch";

import type { paths } from "./schema";

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

/**
 * Typed client generated from the API's OpenAPI document (see `pnpm contracts:generate`).
 * `fetch` is resolved per call so tests and MSW can replace it after import.
 */
export const api = createClient<paths>({
  baseUrl: API_BASE_URL,
  fetch: (request) => globalThis.fetch(request),
});

export type ApiClient = typeof api;

/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_ANON_KEY?: string;
  /** "true" forces MSW, "false" forces the real API. Dev defaults to MSW. */
  readonly VITE_USE_MSW?: string;
}

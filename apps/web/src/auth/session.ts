export interface SessionUser {
  id: string;
  email: string;
  label: string;
  source: "local-stub" | "supabase";
}

const LOCAL_USER: SessionUser = {
  id: "local-researcher",
  email: "researcher@localhost",
  label: "Local researcher",
  source: "local-stub",
};

function envValue(name: "VITE_SUPABASE_URL" | "VITE_SUPABASE_ANON_KEY"): string {
  const value = name === "VITE_SUPABASE_URL" ? import.meta.env.VITE_SUPABASE_URL : import.meta.env.VITE_SUPABASE_ANON_KEY;
  return typeof value === "string" ? value.trim() : "";
}

/** Supabase is optional. An empty anon key keeps the fixture UI on the local stub. */
export function localSession(): SessionUser {
  return LOCAL_USER;
}

export function supabaseConfigured(): boolean {
  return envValue("VITE_SUPABASE_URL").length > 0 && envValue("VITE_SUPABASE_ANON_KEY").length > 0;
}

export async function resolveSession(): Promise<SessionUser> {
  if (!supabaseConfigured()) return LOCAL_USER;
  try {
    const { createClient } = await import("@supabase/supabase-js");
    const client = createClient(envValue("VITE_SUPABASE_URL"), envValue("VITE_SUPABASE_ANON_KEY"), {
      auth: { persistSession: true, autoRefreshToken: true },
    });
    const { data, error } = await client.auth.getSession();
    const email = data.session?.user.email;
    if (error || !data.session || !email) return LOCAL_USER;
    return {
      id: data.session.user.id,
      email,
      label: email,
      source: "supabase",
    };
  } catch {
    return LOCAL_USER;
  }
}

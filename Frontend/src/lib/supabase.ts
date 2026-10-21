import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined;

if (!url || !key) {
  throw new Error("VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY must be set (see Frontend/.env.example)");
}

/**
 * Supabase Auth is the identity provider. Access tokens are short-lived ES256 JWTs; refresh
 * tokens rotate on every use and a reused one revokes the session (server-side reuse detection).
 * The analytics engine never sees passwords or refresh tokens, only the access token.
 */
export const SUPABASE_URL: string = url;
export const SUPABASE_KEY: string = key;

export const supabase = createClient(url, key, {
  auth: {
    flowType: "pkce",
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
});

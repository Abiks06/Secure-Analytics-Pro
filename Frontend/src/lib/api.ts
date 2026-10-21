import { create } from "zustand";
import type {
  AskResult,
  AuditEvent,
  DatasetSummary,
  ProgressEvent,
  PrivacyMode,
  QueryResult,
  Report,
  RowsPage,
  SessionInfo,
  SystemInfo,
  User,
} from "./types";
import type { AuthError, Session } from "@supabase/supabase-js";
import { encryptForUpload } from "./encrypt";
import { SUPABASE_KEY, SUPABASE_URL, supabase } from "./supabase";

/**
 * Session state mirrors Supabase Auth. supabase-js refreshes the access token before it
 * expires (refresh tokens rotate on every use); the store just exposes the current token and
 * user to the rest of the app.
 */
interface AuthState {
  status: "loading" | "authed" | "anon";
  user: User | null;
  token: string | null;
  sessionId: string | null;
  recovering: boolean;
}

export const useAuth = create<AuthState>(() => ({
  status: "loading",
  user: null,
  token: null,
  sessionId: null,
  recovering: false,
}));

function sessionIdOf(token: string): string | null {
  try {
    return JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))).session_id ?? null;
  } catch {
    return null;
  }
}

function apply(session: Session | null) {
  if (!session) {
    useAuth.setState({ status: "anon", user: null, token: null, sessionId: null });
    return;
  }
  const u = session.user;
  const name = (u.user_metadata?.name as string | undefined) || u.email?.split("@")[0] || "Analyst";
  useAuth.setState({
    status: "authed",
    token: session.access_token,
    sessionId: sessionIdOf(session.access_token),
    user: { id: u.id, email: u.email ?? "", name, created_at: u.created_at },
  });
}

/** Restore the persisted session and keep the store in sync with Supabase Auth. */
export function initAuth(): () => void {
  void supabase.auth.getSession().then(({ data }) => apply(data.session));
  const { data } = supabase.auth.onAuthStateChange((event, session) => {
    if (event === "PASSWORD_RECOVERY") useAuth.setState({ recovering: true });
    apply(session);
  });
  return () => data.subscription.unsubscribe();
}

export async function refreshSession(): Promise<boolean> {
  const { data, error } = await supabase.auth.refreshSession();
  apply(error ? null : data.session);
  return !error && !!data.session;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function authError(e: AuthError): ApiError {
  return new ApiError(e.status ?? 400, e.message);
}

async function errorFrom(res: Response): Promise<ApiError> {
  let message = res.statusText || "Request failed";
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") message = body.detail;
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, message);
}

export async function request(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const token = useAuth.getState().token;
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401 && retry && token) {
    if (await refreshSession()) return request(path, init, false);
  }
  if (!res.ok) throw await errorFrom(res);
  return res;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await request(path, init);
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  login: async (email: string, password: string) => {
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw authError(error);
    apply(data.session);
  },
  /** Returns true when the account still needs its email confirmed. */
  register: async (name: string, email: string, password: string): Promise<boolean> => {
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: { data: { name }, emailRedirectTo: `${window.location.origin}/app` },
    });
    if (error) throw authError(error);
    apply(data.session);
    return !data.session;
  },
  resetPassword: async (email: string) => {
    const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: `${window.location.origin}/reset-password` });
    if (error) throw authError(error);
  },
  updatePassword: async (password: string) => {
    const { error } = await supabase.auth.updateUser({ password });
    if (error) throw authError(error);
    useAuth.setState({ recovering: false });
  },
  logout: async (scope: "local" | "global" = "local") => {
    await supabase.auth.signOut({ scope });
    apply(null);
  },
  sessions: () => json<SessionInfo[]>("/api/auth/sessions"),
  revokeSession: (id: string) => json<void>(`/api/auth/sessions/${id}`, { method: "DELETE" }),

  system: () => json<SystemInfo>("/api/system"),
  audit: (before?: number) => json<AuditEvent[]>(`/api/audit?limit=100${before ? `&before=${before}` : ""}`),
  verifyAudit: () => json<{ valid: boolean; events: number; broken_at: number | null; head: string }>("/api/audit/verify"),

  datasets: () => json<DatasetSummary[]>("/api/datasets"),
  dataset: (id: string) => json<DatasetSummary>(`/api/datasets/${id}`),
  report: (id: string) => json<{ dataset: DatasetSummary; report: Report }>(`/api/datasets/${id}/report`),
  rows: (id: string, p: { offset: number; limit: number; sort?: string; desc?: boolean; q?: string }) => {
    const qs = new URLSearchParams({ offset: String(p.offset), limit: String(p.limit) });
    if (p.sort) qs.set("sort", p.sort);
    if (p.desc) qs.set("desc", "true");
    if (p.q) qs.set("q", p.q);
    return json<RowsPage>(`/api/datasets/${id}/rows?${qs}`);
  },
  /**
   * Upload flow: register the dataset, encrypt the file in the browser with a one-time key,
   * upload the ciphertext straight to the user's private Storage folder, then ask the engine to
   * process it while streaming progress back. Plaintext never leaves the browser except inside
   * the TLS request that hands the engine the one-time key.
   */
  upload: async (file: File, handlers: { onUpload?: (fraction: number) => void; onEvent: (e: ProgressEvent) => void }) => {
    const created = await json<DatasetSummary & { upload_path: string; upload_context: string }>("/api/datasets", {
      method: "POST",
      body: JSON.stringify({ name: file.name, size_bytes: file.size }),
    });
    handlers.onEvent({ status: "queued", stage: "encrypt", progress: 0, message: "Encrypting in your browser" });
    const { blob, keyB64 } = await encryptForUpload(file, created.upload_context);
    await putToStorage(created.upload_path, blob, handlers.onUpload);
    const res = await request(`/api/datasets/${created.id}/process`, {
      method: "POST",
      body: JSON.stringify({ key: keyB64 }),
      headers: { Accept: "text/event-stream" },
    });
    await readEvents(res, handlers.onEvent);
    return created as DatasetSummary;
  },
  rename: (id: string, name: string) =>
    json<DatasetSummary>(`/api/datasets/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),
  remove: (id: string) => json<void>(`/api/datasets/${id}`, { method: "DELETE" }),
  query: (id: string, sql: string) =>
    json<QueryResult>(`/api/datasets/${id}/query`, { method: "POST", body: JSON.stringify({ sql }) }),
  ask: (id: string, question: string) =>
    json<AskResult>(`/api/datasets/${id}/ask`, { method: "POST", body: JSON.stringify({ question }) }),
  narrative: (id: string) => json<{ narrative: string }>(`/api/datasets/${id}/narrative`, { method: "POST" }),
  setPrivacy: (id: string, policy: Record<string, PrivacyMode>) =>
    json<DatasetSummary>(`/api/datasets/${id}/privacy`, { method: "PUT", body: JSON.stringify({ policy }) }),
  export: async (id: string, format: "csv" | "parquet" | "json") => {
    const res = await request(`/api/datasets/${id}/export?format=${format}`);
    const blob = await res.blob();
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? `export.${format}`;
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};

/** PUT ciphertext into the caller's Storage folder via XHR, for real upload progress. */
function putToStorage(path: string, blob: Blob, onProgress?: (fraction: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${SUPABASE_URL}/storage/v1/object/datasets/${path}`);
    xhr.setRequestHeader("Authorization", `Bearer ${useAuth.getState().token}`);
    xhr.setRequestHeader("apikey", SUPABASE_KEY);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.setRequestHeader("x-upsert", "false");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) return resolve();
      let message = "Upload to secure storage failed";
      try {
        message = JSON.parse(xhr.responseText).message ?? message;
      } catch {
        /* ignore */
      }
      reject(new ApiError(xhr.status, message));
    };
    xhr.onerror = () => reject(new ApiError(0, "Network error during upload"));
    xhr.send(blob);
  });
}

/** Read a Server-Sent Events response body, calling `onEvent` for each progress event. */
async function readEvents(res: Response, onEvent: (e: ProgressEvent) => void) {
  const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += value;
    let idx: number;
    while ((idx = buffer.search(/\r?\n\r?\n/)) !== -1) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx).replace(/^\r?\n\r?\n/, "");
      const data = chunk
        .split(/\r?\n/)
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trimStart())
        .join("\n");
      if (data) {
        try {
          onEvent(JSON.parse(data) as ProgressEvent);
        } catch {
          /* partial */
        }
      }
    }
  }
}

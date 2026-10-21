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
  TokenResponse,
  User,
} from "./types";

/**
 * The access token lives only in memory (never localStorage), so XSS cannot exfiltrate a
 * long-lived credential. The refresh token is an httpOnly, SameSite=Strict cookie scoped to
 * /api/auth; a page reload silently restores the session through /api/auth/refresh.
 */
interface AuthState {
  status: "loading" | "authed" | "anon";
  user: User | null;
  token: string | null;
  expiresAt: number;
  set: (r: TokenResponse) => void;
  clear: () => void;
}

export const useAuth = create<AuthState>((set) => ({
  status: "loading",
  user: null,
  token: null,
  expiresAt: 0,
  set: (r) => set({ status: "authed", user: r.user, token: r.access_token, expiresAt: r.expires_at }),
  clear: () => set({ status: "anon", user: null, token: null, expiresAt: 0 }),
}));

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let refreshing: Promise<boolean> | null = null;
let refreshTimer: ReturnType<typeof setTimeout> | undefined;

function scheduleRefresh(expiresAt: number) {
  clearTimeout(refreshTimer);
  const ms = Math.max(5_000, expiresAt * 1000 - Date.now() - 60_000);
  refreshTimer = setTimeout(() => void refreshSession(), ms);
}

export function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const res = await fetch("/api/auth/refresh", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-SAP-CSRF": "1" },
      });
      if (!res.ok) {
        useAuth.getState().clear();
        return false;
      }
      const data = (await res.json()) as TokenResponse;
      useAuth.getState().set(data);
      scheduleRefresh(data.expires_at);
      return true;
    } catch {
      useAuth.getState().clear();
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
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
  const res = await fetch(path, { ...init, headers, credentials: "same-origin" });
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

async function authenticate(path: string, body: object): Promise<void> {
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await errorFrom(res);
  const data = (await res.json()) as TokenResponse;
  useAuth.getState().set(data);
  scheduleRefresh(data.expires_at);
}

export const api = {
  login: (email: string, password: string) => authenticate("/api/auth/login", { email, password }),
  register: (name: string, email: string, password: string) =>
    authenticate("/api/auth/register", { name, email, password }),
  logout: async () => {
    clearTimeout(refreshTimer);
    await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin", headers: { "X-SAP-CSRF": "1" } });
    useAuth.getState().clear();
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
  upload: (file: File, onProgress?: (fraction: number) => void) =>
    new Promise<DatasetSummary>((resolve, reject) => {
      // XHR (not fetch) so the UI can show real upload progress.
      const send = (retry: boolean) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/datasets");
        const token = useAuth.getState().token;
        if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
        xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
        xhr.onload = async () => {
          if (xhr.status === 401 && retry && (await refreshSession())) return send(false);
          let body: { detail?: string } & Partial<DatasetSummary> = {};
          try {
            body = JSON.parse(xhr.responseText);
          } catch {
            /* ignore */
          }
          if (xhr.status >= 200 && xhr.status < 300) resolve(body as DatasetSummary);
          else reject(new ApiError(xhr.status, body.detail ?? "Upload failed"));
        };
        xhr.onerror = () => reject(new ApiError(0, "Network error during upload"));
        const form = new FormData();
        form.append("file", file);
        xhr.send(form);
      };
      send(true);
    }),
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

/**
 * Server-Sent Events over fetch (EventSource cannot send an Authorization header).
 * Calls `onEvent` for each progress event until the stream ends or `signal` aborts.
 */
export async function streamProgress(id: string, onEvent: (e: ProgressEvent) => void, signal: AbortSignal) {
  const res = await request(`/api/datasets/${id}/events`, { signal, headers: { Accept: "text/event-stream" } });
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
          /* keep-alive or partial */
        }
      }
    }
  }
}

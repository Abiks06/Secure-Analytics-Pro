import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  CheckCircle2,
  Database,
  Download,
  Eye,
  FileUp,
  Fingerprint,
  KeyRound,
  Laptop,
  Link2,
  LogIn,
  LogOut,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Terminal,
  Trash2,
  XCircle,
} from "lucide-react";
import { motion } from "motion/react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { Badge, Button, Card, CardHeader, cx, Skeleton } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { ago, bytes } from "../lib/format";
import type { AuditEvent } from "../lib/types";

const ACTIONS: Record<string, { label: string; icon: React.ReactNode; tone: string }> = {
  "auth.register": { label: "Account created", icon: <KeyRound className="size-3.5" />, tone: "text-brand-300" },
  "auth.login": { label: "Signed in", icon: <LogIn className="size-3.5" />, tone: "text-mint" },
  "auth.session_started": { label: "Signed in", icon: <LogIn className="size-3.5" />, tone: "text-mint" },
  "auth.login_failed": { label: "Failed sign-in", icon: <ShieldAlert className="size-3.5" />, tone: "text-sev-critical" },
  "auth.logout": { label: "Signed out", icon: <LogOut className="size-3.5" />, tone: "text-fg-muted" },
  "auth.session_revoked": { label: "Session revoked", icon: <XCircle className="size-3.5" />, tone: "text-sev-warning" },
  "auth.refresh_reuse_detected": { label: "Token replay blocked", icon: <ShieldAlert className="size-3.5" />, tone: "text-sev-critical" },
  "dataset.upload": { label: "Dataset uploaded", icon: <FileUp className="size-3.5" />, tone: "text-cyan-glow" },
  "dataset.processed": { label: "Analysis complete", icon: <CheckCircle2 className="size-3.5" />, tone: "text-mint" },
  "dataset.failed": { label: "Analysis failed", icon: <XCircle className="size-3.5" />, tone: "text-sev-critical" },
  "dataset.query": { label: "SQL query", icon: <Terminal className="size-3.5" />, tone: "text-brand-300" },
  "dataset.ask": { label: "AI question", icon: <Sparkles className="size-3.5" />, tone: "text-brand-300" },
  "dataset.export": { label: "Data exported", icon: <Download className="size-3.5" />, tone: "text-sev-warning" },
  "dataset.delete": { label: "Dataset crypto-shredded", icon: <Trash2 className="size-3.5" />, tone: "text-sev-critical" },
  "privacy.update": { label: "Privacy policy changed", icon: <Fingerprint className="size-3.5" />, tone: "text-sev-warning" },
};

function describe(e: AuditEvent): string {
  const d = e.detail as Record<string, unknown>;
  if (e.action === "dataset.upload") return `${d.name} · ${bytes(d.bytes as number)}`;
  if (e.action === "dataset.processed") return `${(d.rows as number)?.toLocaleString()} rows × ${d.columns} cols in ${d.ms} ms`;
  if (e.action === "dataset.ask") return String(d.question ?? "");
  if (e.action === "dataset.query") return `${d.rows} rows returned · sql#${d.sql_sha256}`;
  if (e.action === "dataset.export") return `${String(d.format).toUpperCase()} · ${(d.rows as number)?.toLocaleString()} rows`;
  if (e.action === "privacy.update")
    return Object.entries((d.changes as Record<string, [string, string]>) ?? {})
      .map(([c, [a, b]]) => `${c}: ${a} → ${b}`)
      .join(", ");
  if (e.action === "auth.login_failed") return `attempt #${d.attempt}`;
  if (e.action === "dataset.delete") return String(d.name ?? "");
  if (e.action === "dataset.failed") return String(d.error ?? "");
  return "";
}

function parseUA(ua: string) {
  const browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : "Client";
  const os = /Windows/.test(ua) ? "Windows" : /Mac OS/.test(ua) ? "macOS" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Linux/.test(ua) ? "Linux" : "";
  return `${browser}${os ? ` on ${os}` : ""}`;
}

export default function Security() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const system = useQuery({ queryKey: ["system"], queryFn: api.system });
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api.audit() });
  const verify = useQuery({ queryKey: ["audit-verify"], queryFn: api.verifyAudit });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: api.sessions });
  const revoke = useMutation({
    mutationFn: api.revokeSession,
    onSuccess: () => {
      toast.success("Session revoked");
      qc.invalidateQueries({ queryKey: ["sessions"] });
      qc.invalidateQueries({ queryKey: ["audit"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  const posture = system.data
    ? [
        { icon: <KeyRound className="size-4" />, label: "Encryption at rest", value: system.data.encryption },
        { icon: <ShieldCheck className="size-4" />, label: "Identity", value: system.data.auth },
        { icon: <Activity className="size-4" />, label: "Encrypted file storage", value: system.data.storage },
        { icon: <Database className="size-4" />, label: "Tenant isolation", value: system.data.database === "supabase" ? "Supabase Postgres · forced RLS via a least-privilege engine role" : "Owner-scoped queries (offline mode)" },
        { icon: <Eye className="size-4" />, label: "AI data exposure", value: system.data.ai_enabled ? "Schema, aggregates and masked results only" : "AI disabled" },
      ]
    : [];

  const v = verify.data;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-[-0.03em]">Security Center</h1>
        <p className="mt-1 text-fg-muted">Your tamper-evident activity trail, active sessions and platform security posture.</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
        <div className="min-w-0 space-y-4">
          <Card className={cx("relative overflow-hidden p-5", v && !v.valid && "border-sev-critical/40")}>
            <div className={cx("pointer-events-none absolute -right-20 -top-20 size-64 rounded-full blur-3xl", v?.valid === false ? "bg-sev-critical/20" : "bg-mint/15")} />
            <div className="flex flex-wrap items-center gap-4">
              <div className={cx("grid size-12 place-items-center rounded-2xl", v?.valid === false ? "bg-sev-critical/15 text-sev-critical" : "bg-mint/15 text-mint")}>
                {v?.valid === false ? <ShieldAlert className="size-6" /> : <Link2 className="size-6" />}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-lg font-semibold">
                  {!v ? "Verifying audit chain…" : v.valid ? "Audit chain intact" : `Chain broken at event #${v.broken_at}`}
                </div>
                <div className="mt-0.5 text-[13px] text-fg-muted">
                  {v ? `${v.events} events, each SHA-256-linked to the previous one.` : "Recomputing every hash from genesis."}
                  {v?.valid && (
                    <>
                      {" "}Head <span className="font-mono text-cyan-glow">{v.head.slice(0, 16)}…</span>
                    </>
                  )}
                </div>
              </div>
              <Button variant="secondary" loading={verify.isFetching} onClick={() => verify.refetch()}>
                Re-verify
              </Button>
            </div>
          </Card>

          <Card>
            <CardHeader title="Activity" subtitle="Append-only, hash-chained event log" icon={<Activity className="size-4" />} />
            <div className="p-3">
              {audit.isLoading
                ? Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="m-2 h-12" />)
                : audit.data?.map((e, i) => {
                    const meta = ACTIONS[e.action] ?? { label: e.action, icon: <Activity className="size-3.5" />, tone: "text-fg-muted" };
                    return (
                      <motion.div
                        key={e.seq}
                        initial={{ opacity: 0, x: -6 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: Math.min(i, 15) * 0.02 }}
                        className="group flex items-start gap-3 rounded-xl px-2 py-2.5 hover:bg-white/[0.03]"
                      >
                        <div className={cx("mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg bg-white/[0.05]", meta.tone)}>{meta.icon}</div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-x-2">
                            <span className="text-[14px] font-medium">{meta.label}</span>
                            <span className="text-[12px] text-fg-subtle">{ago(e.created_at)}</span>
                            {e.ip && <span className="font-mono text-[11px] text-fg-subtle">{e.ip}</span>}
                          </div>
                          {describe(e) && <div className="truncate text-[13px] text-fg-muted">{describe(e)}</div>}
                        </div>
                        <div className="hidden shrink-0 text-right font-mono text-[10.5px] leading-tight text-fg-subtle sm:block">
                          <div>#{e.seq}</div>
                          <div className="text-cyan-glow/70 opacity-60 transition group-hover:opacity-100">{e.hash.slice(0, 10)}</div>
                        </div>
                      </motion.div>
                    );
                  })}
            </div>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader
              title="Active sessions"
              subtitle="Supabase Auth · refresh tokens rotate on every use"
              icon={<Laptop className="size-4" />}
              action={
                <Button
                  size="sm"
                  variant="danger"
                  onClick={async () => {
                    if (!window.confirm("Sign out of every device, including this one?")) return;
                    await api.logout("global");
                    navigate("/login");
                  }}
                >
                  Sign out everywhere
                </Button>
              }
            />
            <div className="space-y-1 p-3">
              {sessions.data?.map((s) => (
                <div key={s.id} className="flex items-center gap-3 rounded-xl px-2 py-2.5">
                  <div className="grid size-8 place-items-center rounded-lg bg-white/[0.05]">
                    <Laptop className="size-4 text-fg-muted" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-[13.5px] font-medium">
                      {parseUA(s.user_agent)} {s.current && <Badge tone="positive">this device</Badge>}
                    </div>
                    <div className="text-[12px] text-fg-subtle">
                      {s.ip || "unknown IP"}
                      {s.last_used_at && <> · active {ago(s.last_used_at)}</>}
                      {s.aal === "aal2" && <> · MFA</>}
                    </div>
                  </div>
                  {!s.current && (
                    <Button size="sm" variant="danger" loading={revoke.isPending && revoke.variables === s.id} onClick={() => revoke.mutate(s.id)}>
                      Revoke
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </Card>
          <Card>
            <CardHeader title="Security posture" icon={<ShieldCheck className="size-4" />} />
            <div className="space-y-3 p-5">
              {posture.map((p) => (
                <div key={p.label} className="flex gap-3">
                  <div className="mt-0.5 text-mint">{p.icon}</div>
                  <div>
                    <div className="text-[13px] font-medium">{p.label}</div>
                    <div className="text-[12.5px] text-fg-muted">{p.value}</div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

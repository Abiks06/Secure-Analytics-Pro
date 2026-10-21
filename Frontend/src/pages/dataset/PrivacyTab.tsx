import { useMutation, useQueryClient } from "@tanstack/react-query";
import { EyeOff, Fingerprint, Hash, ScanEye, ShieldAlert, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Badge, Button, Card, CardHeader, cx, Empty } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { pct } from "../../lib/format";
import type { DatasetSummary, PrivacyMode, Report } from "../../lib/types";

const MODES: { id: PrivacyMode; label: string; icon: React.ReactNode; example: string; desc: string }[] = [
  { id: "none", label: "Visible", icon: <ScanEye className="size-3.5" />, example: "ann.lee@acme.com", desc: "Shown as-is" },
  { id: "mask", label: "Mask", icon: <EyeOff className="size-3.5" />, example: "a•••@a•••.com", desc: "Partially hidden, format kept" },
  { id: "hash", label: "Pseudonymise", icon: <Hash className="size-3.5" />, example: "anon_3f9a1c07d2e4", desc: "Keyed HMAC: joinable, irreversible" },
  { id: "redact", label: "Redact", icon: <ShieldAlert className="size-3.5" />, example: "[REDACTED]", desc: "Removed entirely" },
];

const RISK_TONE = { critical: "critical", high: "warning", medium: "notable", low: "info" } as const;

export default function PrivacyTab({ ds, report }: { ds: DatasetSummary; report: Report }) {
  const qc = useQueryClient();
  const [policy, setPolicy] = useState<Record<string, PrivacyMode>>(ds.privacy_policy);
  const [showAll, setShowAll] = useState(false);
  const findings = report.privacy.findings;
  const flagged = new Set(findings.map((f) => f.column));
  const otherColumns = report.columns.filter((c) => !flagged.has(c.name) && (c.kind === "text" || c.kind === "identifier" || c.kind === "categorical"));
  const dirty = useMemo(() => JSON.stringify(policy) !== JSON.stringify(ds.privacy_policy), [policy, ds.privacy_policy]);
  const protectedCount = Object.values(policy).filter((m) => m !== "none").length;

  const save = useMutation({
    mutationFn: () => api.setPrivacy(ds.id, policy),
    onSuccess: (d) => {
      qc.setQueryData(["dataset", ds.id], d);
      qc.invalidateQueries({ queryKey: ["rows", ds.id] });
      toast.success("Privacy policy applied", { description: "Previews, SQL, AI and exports now use the new policy. Change recorded in the audit log." });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not save policy"),
  });

  const Picker = ({ column }: { column: string }) => (
    <div className="flex flex-wrap gap-1 rounded-xl bg-white/[0.04] p-1">
      {MODES.map((m) => {
        const active = (policy[column] ?? "none") === m.id;
        return (
          <button
            key={m.id}
            title={m.desc}
            onClick={() => setPolicy((p) => ({ ...p, [column]: m.id }))}
            className={cx(
              "flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[12.5px] font-medium transition",
              active ? (m.id === "none" ? "bg-white/10 text-fg" : "bg-brand-500/20 text-brand-300 ring-1 ring-brand-400/30") : "text-fg-subtle hover:text-fg-muted",
            )}
          >
            {m.icon}
            {m.label}
          </button>
        );
      })}
    </div>
  );

  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
      <div className="min-w-0 space-y-4">
        <Card>
          <CardHeader
            title="Detected personal data"
            subtitle="Pattern matching with checksum validation, combined with column semantics"
            icon={<Fingerprint className="size-4" />}
            action={
              <Button variant="primary" size="sm" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
                Apply policy
              </Button>
            }
          />
          {findings.length === 0 ? (
            <Empty icon={<ShieldCheck className="size-5" />} title="No personal data detected" body="You can still protect any column manually below." />
          ) : (
            <div className="divide-y divide-white/[0.06] px-5 pb-2 pt-3">
              {findings.map((f) => (
                <div key={f.column} className="flex flex-col gap-3 py-4 lg:flex-row lg:items-center">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-[14px] font-medium">{f.column}</span>
                      <Badge tone={RISK_TONE[f.risk]}>{f.risk}</Badge>
                    </div>
                    <div className="mt-1 text-[13px] text-fg-muted">
                      {f.label} · {pct(f.confidence)} confidence · via {f.evidence}
                      {f.match_ratio != null && ` (${pct(f.match_ratio)} of sampled values match)`}
                    </div>
                  </div>
                  <Picker column={f.column} />
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card>
          <button onClick={() => setShowAll((v) => !v)} className="flex w-full items-center justify-between px-5 py-4 text-left">
            <div>
              <div className="font-semibold">Other text columns</div>
              <div className="text-[13px] text-fg-subtle">{otherColumns.length} columns not flagged. Protect them manually if they're sensitive.</div>
            </div>
            <span className="text-[13px] text-brand-300">{showAll ? "Hide" : "Show"}</span>
          </button>
          {showAll && (
            <div className="divide-y divide-white/[0.06] border-t border-white/[0.06] px-5">
              {otherColumns.map((c) => (
                <div key={c.name} className="flex flex-col gap-3 py-3 lg:flex-row lg:items-center">
                  <span className="flex-1 font-mono text-[13.5px]">{c.name}</span>
                  <Picker column={c.name} />
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
      <div className="space-y-4">
        <Card className="relative overflow-hidden p-5">
          <div className="pointer-events-none absolute -right-16 -top-16 size-48 rounded-full bg-mint/15 blur-3xl" />
          <ShieldCheck className="size-8 text-mint" />
          <div className="mt-3 text-3xl font-semibold">{protectedCount}</div>
          <div className="text-[13px] text-fg-muted">columns protected</div>
          <p className="mt-4 text-[13px] leading-relaxed text-fg-muted">
            The policy is enforced server-side before data reaches the table view, the SQL sandbox, the AI analyst or any export.
            Pseudonyms use a per-dataset HMAC key, so the same email always maps to the same token and joins and counts still work.
          </p>
        </Card>
        <Card className="p-5">
          <h3 className="font-semibold">Modes</h3>
          <div className="mt-3 space-y-3">
            {MODES.map((m) => (
              <div key={m.id} className="text-[13px]">
                <div className="flex items-center gap-2 font-medium text-fg">
                  {m.icon} {m.label}
                </div>
                <div className="mt-0.5 font-mono text-[12px] text-fg-subtle">{m.example}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

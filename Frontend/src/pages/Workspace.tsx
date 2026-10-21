import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowUpRight, Database, Fingerprint, Gauge, Layers, Lightbulb, Rows3, Search, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { UploadPanel } from "../components/UploadPanel";
import { Badge, Card, Empty, Input, QualityRing, SeverityDot, Skeleton, Stat } from "../components/ui";
import { api, useAuth } from "../lib/api";
import { ago, bytes, compact, ms, qualityTone } from "../lib/format";
import type { DatasetSummary } from "../lib/types";

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

function DatasetCard({ d, i }: { d: DatasetSummary; i: number }) {
  const tone = qualityTone(d.quality_score);
  const busy = d.status === "queued" || d.status === "processing";
  return (
    <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i, 8) * 0.04, duration: 0.45, ease: [0.22, 1, 0.36, 1] }}>
      <Link to={`/app/datasets/${d.id}`} className="group block h-full">
        <Card className="relative h-full overflow-hidden p-5 transition duration-300 group-hover:-translate-y-0.5 group-hover:border-white/15">
          <div className="pointer-events-none absolute -right-16 -top-16 size-40 rounded-full opacity-0 blur-3xl transition duration-500 group-hover:opacity-30" style={{ background: tone.hex }} />
          <div className="flex items-start gap-4">
            {d.status === "ready" ? (
              <QualityRing score={d.quality_score} size={54} stroke={5} />
            ) : (
              <div className="grid size-[54px] place-items-center rounded-full bg-white/[0.04]">
                {d.status === "failed" ? <AlertTriangle className="size-5 text-sev-critical" /> : <Skeleton className="size-8 rounded-full" />}
              </div>
            )}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h3 className="truncate font-semibold tracking-tight">{d.name}</h3>
                <ArrowUpRight className="size-4 shrink-0 text-fg-subtle opacity-0 transition group-hover:opacity-100" />
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-fg-subtle">
                {d.status === "ready" ? (
                  <>
                    <span className="font-mono">{compact(d.row_count)} × {d.column_count}</span>
                    <span>{bytes(d.size_bytes)}</span>
                    <span>{ago(d.created_at)}</span>
                  </>
                ) : (
                  <span className={d.status === "failed" ? "text-sev-critical" : "text-brand-300"}>
                    {d.status === "failed" ? d.error ?? "Failed" : `Processing · ${d.stage}`}
                  </span>
                )}
              </div>
            </div>
          </div>
          {d.status === "ready" && (
            <>
              <div className="mt-4 space-y-1.5">
                {d.top_insights.slice(0, 2).map((t) => (
                  <div key={t.title} className="flex items-center gap-2 text-[13px] text-fg-muted">
                    <SeverityDot severity={t.severity} />
                    <span className="truncate">{t.title}</span>
                  </div>
                ))}
              </div>
              <div className="mt-4 flex flex-wrap gap-1.5">
                <Badge tone="brand">
                  <Lightbulb className="size-3" /> {d.insight_count} insights
                </Badge>
                {d.pii_count > 0 && (
                  <Badge tone="critical">
                    <Fingerprint className="size-3" /> {d.pii_count} PII
                  </Badge>
                )}
                <Badge>{d.source_format.toUpperCase()}</Badge>
                {d.processing_ms != null && <Badge>{ms(d.processing_ms)}</Badge>}
              </div>
            </>
          )}
          {busy && <div className="absolute inset-x-0 bottom-0 h-0.5 skeleton" />}
        </Card>
      </Link>
    </motion.div>
  );
}

export default function Workspace() {
  const user = useAuth((s) => s.user);
  const [q, setQ] = useState("");
  const { data: datasets, isLoading } = useQuery({
    queryKey: ["datasets"],
    queryFn: api.datasets,
    refetchInterval: (query) => (query.state.data?.some((d) => d.status === "queued" || d.status === "processing") ? 2000 : false),
  });
  const { data: system } = useQuery({ queryKey: ["system"], queryFn: api.system });
  const filtered = useMemo(() => (datasets ?? []).filter((d) => d.name.toLowerCase().includes(q.toLowerCase())), [datasets, q]);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-fg-subtle">{greeting()},</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-[-0.03em]">{user?.name?.split(" ")[0]}'s workspace</h1>
        </div>
        {system?.ai_enabled && (
          <Badge tone="positive" className="!px-3 !py-1 !text-[12px]">
            <Sparkles className="size-3.5" /> AI analyst ready
          </Badge>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Datasets" icon={<Layers className="size-3.5" />} value={system?.usage.datasets ?? "—"} hint="analysed & encrypted" accent="#8b7bff" />
        <Stat label="Rows" icon={<Rows3 className="size-3.5" />} value={compact(system?.usage.rows)} hint="cleaned and profiled" accent="#22d3ee" />
        <Stat label="Avg quality" icon={<Gauge className="size-3.5" />} value={system?.usage.avg_quality ?? "—"} hint={qualityTone(system?.usage.avg_quality).label} accent={qualityTone(system?.usage.avg_quality).hex} />
        <Stat label="Encrypted" icon={<Database className="size-3.5" />} value={bytes(system?.usage.stored_bytes)} hint="AES-256-GCM at rest" accent="#34d399" />
      </div>

      <UploadPanel maxMb={system?.max_upload_mb} />

      <section>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold tracking-tight">Datasets</h2>
          <div className="w-full sm:w-64">
            <Input icon={<Search className="size-4" />} placeholder="Filter datasets" value={q} onChange={(e) => setQ(e.target.value)} className="h-9 text-sm" />
          </div>
        </div>
        {isLoading ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-44 rounded-xl2" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <Card>
            <Empty icon={<Database className="size-5" />} title={datasets?.length ? "No matches" : "No datasets yet"} body={datasets?.length ? "Try a different filter." : "Upload a file above, or try the messy sample to see the engine at work."} />
          </Card>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {filtered.map((d, i) => (
              <DatasetCard key={d.id} d={d} i={i} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Bot, CheckCircle2, Clock, Copy, Eraser, FileCode2, Gauge, Rows3, Sparkles, Wand2 } from "lucide-react";
import { motion } from "motion/react";
import { toast } from "sonner";
import { InsightCard } from "../../components/InsightCard";
import { Button, Card, CardHeader, Meter, QualityRing } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { compact, ms, pct, qualityTone } from "../../lib/format";
import type { DatasetSummary, Report } from "../../lib/types";

const ACTION_ICON: Record<string, React.ReactNode> = {
  cast_numeric: <span className="font-mono text-[10px]">123</span>,
  cast_datetime: <Clock className="size-3" />,
  cast_boolean: <CheckCircle2 className="size-3" />,
  drop_duplicates: <Copy className="size-3" />,
  unify_categories: <Wand2 className="size-3" />,
  normalise_nulls: <Eraser className="size-3" />,
};

function QualityCard({ report }: { report: Report }) {
  const q = report.quality;
  const tone = qualityTone(q.score);
  const dims = [
    ["Completeness", q.completeness, "Share of cells with a value"],
    ["Validity", q.validity, "Values that parsed as their inferred type"],
    ["Uniqueness", q.uniqueness, "Penalises exact duplicate rows"],
    ["Consistency", q.consistency, "Uniform formats, casing and spacing"],
  ] as const;
  return (
    <Card className="p-5">
      <div className="flex items-center gap-5">
        <QualityRing score={q.score} size={92} stroke={7} />
        <div>
          <div className="text-[12px] uppercase tracking-[0.1em] text-fg-subtle">Source data quality</div>
          <div className="mt-1 text-2xl font-semibold" style={{ color: tone.hex }}>
            {tone.label}
          </div>
          <p className="mt-1 text-[13px] text-fg-muted">Scored before cleaning. Everything below has been fixed.</p>
        </div>
      </div>
      <div className="mt-6 space-y-3.5">
        {dims.map(([label, v, hint]) => (
          <div key={label} title={hint}>
            <div className="mb-1.5 flex justify-between text-[13px]">
              <span className="text-fg-muted">{label}</span>
              <span className="font-mono tabular">{pct(v, 1)}</span>
            </div>
            <Meter value={v} color={qualityTone(v * 100).hex} />
          </div>
        ))}
      </div>
    </Card>
  );
}

function Narrative({ ds, report }: { ds: DatasetSummary; report: Report }) {
  const qc = useQueryClient();
  const system = useQuery({ queryKey: ["system"], queryFn: api.system });
  const gen = useMutation({
    mutationFn: () => api.narrative(ds.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["report", ds.id] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not generate summary"),
  });
  const text = gen.data?.narrative ?? report.narrative;
  return (
    <Card className="ring-gradient relative overflow-hidden p-5">
      <div className="pointer-events-none absolute -right-24 -top-24 size-64 rounded-full bg-brand-500/15 blur-3xl" />
      <div className="flex items-center gap-2">
        <div className="grid size-8 place-items-center rounded-lg bg-brand-gradient text-white">
          <Bot className="size-4" />
        </div>
        <h3 className="font-semibold">Executive summary</h3>
        {system.data?.ai_model && <span className="ml-auto font-mono text-[11px] text-fg-subtle">{system.data.ai_model}</span>}
      </div>
      {text ? (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-4 space-y-3 text-[14.5px] leading-relaxed text-fg-muted">
          {text.split(/\n{2,}/).map((p, i) => (
            <p key={i}>{p}</p>
          ))}
        </motion.div>
      ) : (
        <div className="mt-4">
          <p className="text-[14px] text-fg-muted">
            Have Claude write a plain-English brief from the {report.insights.length} findings. It sees aggregates only, never raw rows.
          </p>
          <Button className="mt-4" variant="primary" icon={<Sparkles className="size-4" />} loading={gen.isPending} disabled={!system.data?.ai_enabled} onClick={() => gen.mutate()}>
            {system.data?.ai_enabled ? "Generate summary" : "AI analyst offline"}
          </Button>
          {!system.data?.ai_enabled && <p className="mt-2 text-[12px] text-fg-subtle">Set ANTHROPIC_API_KEY on the server to enable.</p>}
        </div>
      )}
    </Card>
  );
}

export default function Overview({ ds, report, goTo }: { ds: DatasetSummary; report: Report; goTo: (t: "insights" | "columns") => void }) {
  const o = report.overview;
  const kinds = Object.entries(o.kinds).sort((a, b) => b[1] - a[1]);
  const top = report.insights.slice(0, 4);
  const timings = Object.entries(report.timings_ms).filter(([k]) => k !== "total");
  const totalMs = report.timings_ms.total ?? timings.reduce((s, [, v]) => s + v, 0);
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
      <div className="min-w-0 space-y-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[
            { icon: <Rows3 className="size-4" />, label: "Rows", value: o.rows.toLocaleString(), hint: o.rows_raw !== o.rows ? `${(o.rows_raw - o.rows).toLocaleString()} removed` : "none removed" },
            { icon: <FileCode2 className="size-4" />, label: "Columns", value: o.columns, hint: kinds.map(([k, n]) => `${n} ${k}`).slice(0, 2).join(" · ") },
            { icon: <Gauge className="size-4" />, label: "Missing", value: pct(o.missing_pct, 1), hint: `${compact(o.missing_cells)} cells` },
            { icon: <Wand2 className="size-4" />, label: "Auto-fixes", value: report.cleaning.actions.length, hint: `${compact(report.cleaning.actions.reduce((s, a) => s + a.count, 0))} values touched` },
          ].map((s) => (
            <Card key={s.label} className="p-4">
              <div className="flex items-center gap-2 text-[12px] uppercase tracking-[0.08em] text-fg-subtle">
                {s.icon} {s.label}
              </div>
              <div className="mt-2 font-mono text-2xl font-semibold tabular">{s.value}</div>
              <div className="mt-0.5 truncate text-[12px] text-fg-muted">{s.hint}</div>
            </Card>
          ))}
        </div>

        <div className="flex items-center justify-between pt-2">
          <h2 className="text-lg font-semibold tracking-tight">Top findings</h2>
          <button onClick={() => goTo("insights")} className="flex items-center gap-1 text-[13px] text-brand-300 hover:text-brand-400">
            All {report.insights.length} insights <ArrowRight className="size-3.5" />
          </button>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {top.map((ins, i) => (
            <InsightCard key={ins.id} insight={ins} i={i} chartHeight={170} />
          ))}
        </div>
      </div>

      <div className="space-y-4">
        <QualityCard report={report} />
        <Narrative ds={ds} report={report} />
        <Card>
          <CardHeader title="Cleaning log" subtitle={`${report.cleaning.actions.length} automatic repairs`} icon={<Wand2 className="size-4" />} />
          <ol className="relative mx-5 mb-5 mt-4 space-y-3 border-l border-white/[0.08] pl-5">
            {report.cleaning.actions.slice(0, 12).map((a, i) => (
              <li key={i} className="relative">
                <span className="absolute -left-[27px] top-0.5 grid size-[15px] place-items-center rounded-full bg-ink-800 text-brand-300 ring-1 ring-white/10">
                  {ACTION_ICON[a.action] ?? <span className="size-1 rounded-full bg-brand-300" />}
                </span>
                <div className="text-[13px]">
                  {a.column && <span className="mr-1.5 rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[11px] text-fg">{a.column}</span>}
                  <span className="text-fg-muted">{a.detail}</span>
                  {a.count > 0 && <span className="ml-1 font-mono text-[11px] text-fg-subtle">×{a.count.toLocaleString()}</span>}
                </div>
              </li>
            ))}
            {report.ingest.notes.map((n) => (
              <li key={n} className="text-[13px] text-sev-info">{n}</li>
            ))}
          </ol>
        </Card>
        <Card className="p-5">
          <div className="flex items-baseline justify-between">
            <h3 className="font-semibold">Pipeline timing</h3>
            <span className="font-mono text-sm text-mint">{ms(totalMs)}</span>
          </div>
          <div className="mt-4 flex h-2.5 overflow-hidden rounded-full bg-white/[0.05]">
            {timings.map(([k, v], i) => (
              <div key={k} title={`${k}: ${ms(v)}`} style={{ width: `${(v / Math.max(1, totalMs)) * 100}%`, background: ["#8b7bff", "#22d3ee", "#34d399", "#fbbf24", "#fb7185", "#60a5fa"][i % 6] }} />
            ))}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-[12px]">
            {timings.map(([k, v], i) => (
              <div key={k} className="flex items-center gap-2 text-fg-muted">
                <span className="size-2 rounded-sm" style={{ background: ["#8b7bff", "#22d3ee", "#34d399", "#fbbf24", "#fb7185", "#60a5fa"][i % 6] }} />
                <span className="capitalize">{k}</span>
                <span className="ml-auto font-mono text-fg-subtle">{ms(v)}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

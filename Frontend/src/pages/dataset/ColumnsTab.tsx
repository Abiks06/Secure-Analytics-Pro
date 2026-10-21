import { Binary, Calendar, Hash, KeyRound, Search, ToggleLeft, Type, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { HistogramView, MiniBars } from "../../components/charts";
import { Badge, Card, cx, Input, Meter } from "../../components/ui";
import { compact, dateLabel, num, pct, withUnit } from "../../lib/format";
import type { ColumnProfile, Report } from "../../lib/types";

const KIND: Record<ColumnProfile["kind"], { icon: React.ReactNode; color: string }> = {
  numeric: { icon: <Hash className="size-3.5" />, color: "#8b7bff" },
  datetime: { icon: <Calendar className="size-3.5" />, color: "#22d3ee" },
  boolean: { icon: <ToggleLeft className="size-3.5" />, color: "#34d399" },
  categorical: { icon: <Binary className="size-3.5" />, color: "#fbbf24" },
  text: { icon: <Type className="size-3.5" />, color: "#f472b6" },
  identifier: { icon: <KeyRound className="size-3.5" />, color: "#6e7593" },
};

function Preview({ c }: { c: ColumnProfile }) {
  const color = KIND[c.kind].color;
  if (c.histogram?.counts.length) return <MiniBars values={c.histogram.counts} color={color} />;
  if (c.timeline?.n.length) return <MiniBars values={c.timeline.n} color={color} />;
  if (c.top?.length) {
    const total = c.count || 1;
    return (
      <div className="space-y-1">
        {c.top.slice(0, 3).map((t) => (
          <div key={String(t.value)} className="flex items-center gap-2 text-[11.5px]">
            <span className="w-20 truncate text-fg-muted">{String(t.value)}</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.05]">
              <div className="h-full rounded-full" style={{ width: `${(t.count / total) * 100}%`, background: color }} />
            </div>
          </div>
        ))}
      </div>
    );
  }
  return <div className="h-9" />;
}

function headline(c: ColumnProfile): string {
  const s = c.stats ?? {};
  if (c.kind === "numeric") return `${withUnit(s.min as number, c.unit)} → ${withUnit(s.max as number, c.unit)}`;
  if (c.kind === "datetime") return `${String(s.min).slice(0, 10)} → ${String(s.max).slice(0, 10)}`;
  return `${compact(c.distinct)} distinct`;
}

function Detail({ c, onClose }: { c: ColumnProfile; onClose: () => void }) {
  const s = c.stats ?? {};
  const rows: [string, string][] =
    c.kind === "numeric"
      ? [
          ["Mean", withUnit(s.mean as number, c.unit)],
          ["Median", withUnit(s.q50 as number, c.unit)],
          ["Std dev", num(s.std as number)],
          ["Min / Max", `${withUnit(s.min as number, c.unit)} / ${withUnit(s.max as number, c.unit)}`],
          ["P5 / P95", `${withUnit(s.q05 as number, c.unit)} / ${withUnit(s.q95 as number, c.unit)}`],
          ["IQR", `${withUnit(s.q25 as number, c.unit)} – ${withUnit(s.q75 as number, c.unit)}`],
          ["Sum", withUnit(s.sum as number, c.unit)],
          ["Skew / Kurtosis", `${num(s.skew as number)} / ${num(s.kurtosis as number)}`],
          ["Zeros / Negatives", `${compact(s.zeros as number)} / ${compact(s.negatives as number)}`],
        ]
      : c.kind === "datetime"
        ? [
            ["First", String(s.min)],
            ["Last", String(s.max)],
            ["Granularity", String(s.granularity)],
          ]
        : [
            ["Distinct", compact(c.distinct)],
            ["Entropy", c.entropy != null ? pct(c.entropy) : "—"],
            ["Length", c.length ? `${c.length.min}–${c.length.max} (avg ${num(c.length.mean, 1)})` : "—"],
          ];
  return (
    <motion.div className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
      <motion.aside
        initial={{ x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ type: "spring", bounce: 0, duration: 0.4 }}
        onClick={(e) => e.stopPropagation()}
        className="glass-strong h-full w-full max-w-lg overflow-y-auto p-6"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-[12px] uppercase tracking-[0.1em]" style={{ color: KIND[c.kind].color }}>
              {KIND[c.kind].icon} {c.kind}
            </div>
            <h2 className="mt-1 text-xl font-semibold">{c.name}</h2>
            {c.original_name !== c.name && <p className="mt-0.5 font-mono text-[12px] text-fg-subtle">originally “{c.original_name}”</p>}
          </div>
          <button onClick={onClose} aria-label="Close" className="grid size-8 place-items-center rounded-lg hover:bg-white/[0.06]">
            <X className="size-4" />
          </button>
        </div>
        <div className="mt-5 flex flex-wrap gap-1.5">
          <Badge>{c.dtype}</Badge>
          {c.unit && <Badge tone="brand">{c.unit.replace("currency:", "currency ")}</Badge>}
          <Badge tone={c.null_pct > 0.3 ? "warning" : "neutral"}>{pct(c.null_pct, 1)} missing</Badge>
          {c.invalid > 0 && <Badge tone="critical">{c.invalid} invalid</Badge>}
        </div>
        <Card className="mt-5 p-4">
          {c.histogram ? (
            <HistogramView bins={c.histogram.bins} counts={c.histogram.counts} height={200} color={KIND[c.kind].color} />
          ) : c.timeline ? (
            <div>
              <MiniBars values={c.timeline.n} color={KIND[c.kind].color} height={140} />
              <div className="mt-2 flex justify-between text-[11px] text-fg-subtle">
                <span>{dateLabel(c.timeline.t[0], "1mo")}</span>
                <span>{dateLabel(c.timeline.t[c.timeline.t.length - 1], "1mo")}</span>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {c.top?.map((t) => (
                <div key={String(t.value)} className="text-[13px]">
                  <div className="mb-1 flex justify-between">
                    <span className="truncate text-fg-muted">{String(t.value)}</span>
                    <span className="font-mono text-fg-subtle">{t.count.toLocaleString()}</span>
                  </div>
                  <Meter value={t.count / Math.max(1, c.count)} color={KIND[c.kind].color} />
                </div>
              ))}
              {!!c.other_count && <div className="pt-1 text-[12px] text-fg-subtle">+ {c.other_count.toLocaleString()} in other values</div>}
            </div>
          )}
        </Card>
        <dl className="mt-5 divide-y divide-white/[0.06] rounded-xl border border-white/[0.07]">
          {[["Values", c.count.toLocaleString()], ["Missing", c.nulls.toLocaleString()], ...rows].map(([k, v]) => (
            <div key={k} className="flex justify-between gap-4 px-4 py-2.5 text-[13.5px]">
              <dt className="text-fg-subtle">{k}</dt>
              <dd className="truncate font-mono text-fg">{v}</dd>
            </div>
          ))}
        </dl>
      </motion.aside>
    </motion.div>
  );
}

export default function ColumnsTab({ report }: { report: Report }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<ColumnProfile | null>(null);
  const cols = useMemo(() => report.columns.filter((c) => c.name.toLowerCase().includes(q.toLowerCase())), [report, q]);
  const pii = new Set(report.privacy.findings.map((f) => f.column));
  return (
    <div className="space-y-5">
      <div className="w-full sm:w-72">
        <Input icon={<Search className="size-4" />} placeholder="Search columns" value={q} onChange={(e) => setQ(e.target.value)} className="h-9 text-sm" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
        {cols.map((c, i) => (
          <motion.button
            key={c.name}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: Math.min(i, 16) * 0.02 }}
            onClick={() => setOpen(c)}
            className="glass group rounded-xl2 p-4 text-left transition hover:-translate-y-0.5 hover:border-white/15"
          >
            <div className="flex items-center gap-2">
              <span className="grid size-6 place-items-center rounded-md bg-white/[0.05]" style={{ color: KIND[c.kind].color }}>
                {KIND[c.kind].icon}
              </span>
              <span className="truncate font-medium">{c.name}</span>
              {pii.has(c.name) && <Badge tone="critical" className="ml-auto">PII</Badge>}
            </div>
            <div className="mt-1 truncate font-mono text-[12px] text-fg-subtle">{headline(c)}</div>
            <div className="mt-3">
              <Preview c={c} />
            </div>
            <div className="mt-3 flex items-center gap-2">
              <div className="flex-1">
                <Meter value={c.health.completeness} color={c.health.completeness > 0.95 ? "#34d399" : c.health.completeness > 0.7 ? "#fbbf24" : "#fb7185"} />
              </div>
              <span className={cx("font-mono text-[11px]", c.null_pct > 0.3 ? "text-sev-warning" : "text-fg-subtle")}>{pct(c.health.completeness)}</span>
            </div>
          </motion.button>
        ))}
      </div>
      <AnimatePresence>{open && <Detail c={open} onClose={() => setOpen(null)} />}</AnimatePresence>
    </div>
  );
}

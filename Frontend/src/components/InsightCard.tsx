import { motion } from "motion/react";
import { num, pct, severityStyle } from "../lib/format";
import type { Insight } from "../lib/types";
import { InsightChart } from "./charts";
import { Card, cx, SeverityDot } from "./ui";

const KIND_LABEL: Record<string, string> = {
  correlation: "Correlation",
  redundancy: "Redundancy",
  outlier: "Outliers",
  anomaly: "Anomaly",
  segment: "Driver",
  pareto: "Concentration",
  distribution: "Distribution",
  quality: "Data quality",
  trend: "Trend",
  seasonality: "Seasonality",
  privacy: "Privacy",
};

function metricValue(m: Insight["metric"]) {
  if (!m) return null;
  const v = m.value;
  if (/share|missing|change/.test(m.label)) return pct(v, 1);
  return num(v, 3);
}

export function InsightCard({ insight, i = 0, chartHeight = 190, compact = false }: { insight: Insight; i?: number; chartHeight?: number; compact?: boolean }) {
  const sev = severityStyle[insight.severity];
  return (
    <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i, 10) * 0.035, duration: 0.45, ease: [0.22, 1, 0.36, 1] }} className="h-full">
      <Card className="group relative flex h-full flex-col overflow-hidden p-5 transition duration-300 hover:border-white/15">
        <div className="absolute inset-y-0 left-0 w-[3px] opacity-80" style={{ background: `linear-gradient(${sev.hex}, transparent)` }} />
        <div className="flex items-center gap-2">
          <SeverityDot severity={insight.severity} />
          <span className={cx("text-[11px] font-semibold uppercase tracking-[0.1em]", sev.text)}>{KIND_LABEL[insight.kind] ?? insight.kind}</span>
          <span className="ml-auto flex items-center gap-1.5 font-mono text-[11px] text-fg-subtle" title="Relevance score">
            <span className="h-1 w-10 overflow-hidden rounded-full bg-white/[0.07]">
              <span className="block h-full rounded-full bg-brand-400" style={{ width: `${insight.score * 100}%` }} />
            </span>
            {Math.round(insight.score * 100)}
          </span>
        </div>
        <h3 className="mt-3 text-[15.5px] font-semibold leading-snug tracking-tight">{insight.title}</h3>
        <p className={cx("mt-2 text-[13.5px] leading-relaxed text-fg-muted", compact && "line-clamp-3")}>{insight.body}</p>
        {insight.chart && !compact && (
          <div className="-mx-1 mt-4">
            <InsightChart spec={insight.chart} height={chartHeight} />
          </div>
        )}
        <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-4">
          {insight.columns.slice(0, 4).map((c) => (
            <span key={c} className="rounded-md bg-white/[0.05] px-1.5 py-0.5 font-mono text-[11px] text-fg-subtle">
              {c}
            </span>
          ))}
          {insight.metric && (
            <span className="ml-auto text-[12px] text-fg-subtle">
              {insight.metric.label} <span className="font-mono text-fg">{metricValue(insight.metric)}</span>
            </span>
          )}
        </div>
      </Card>
    </motion.div>
  );
}

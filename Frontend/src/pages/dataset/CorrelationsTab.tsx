import { GitCompareArrows, Radar } from "lucide-react";
import { useState } from "react";
import { Heatmap } from "../../components/charts";
import { Card, CardHeader, cx, Empty } from "../../components/ui";
import { num } from "../../lib/format";
import type { Report } from "../../lib/types";

function strength(r: number) {
  const a = Math.abs(r);
  return a >= 0.8 ? "very strong" : a >= 0.6 ? "strong" : a >= 0.4 ? "moderate" : a >= 0.2 ? "weak" : "negligible";
}

export default function CorrelationsTab({ report }: { report: Report }) {
  const [method, setMethod] = useState<"pearson" | "spearman">("spearman");
  const [sel, setSel] = useState<[string, string] | null>(null);
  const corr = report.correlations;
  const mv = report.outliers.multivariate;
  if (!corr) {
    return (
      <Card>
        <Empty icon={<GitCompareArrows className="size-5" />} title="Not enough numeric columns" body="Correlation analysis needs at least two numeric columns." />
      </Card>
    );
  }
  const pair = sel ? corr.top_pairs.find((p) => (p.a === sel[0] && p.b === sel[1]) || (p.a === sel[1] && p.b === sel[0])) : null;
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
      <Card className="min-w-0">
        <CardHeader
          title="Correlation matrix"
          subtitle={method === "spearman" ? "Spearman ρ: rank-based, robust to outliers and non-linear trends" : "Pearson r: linear association"}
          icon={<GitCompareArrows className="size-4" />}
          action={
            <div className="flex rounded-lg bg-white/[0.05] p-0.5 text-[12px]">
              {(["spearman", "pearson"] as const).map((m) => (
                <button key={m} onClick={() => setMethod(m)} className={cx("rounded-md px-2.5 py-1 capitalize transition", method === m ? "bg-white/10 text-fg" : "text-fg-subtle")}>
                  {m}
                </button>
              ))}
            </div>
          }
        />
        <div className="p-5">
          <Heatmap labels={corr.columns} matrix={corr[method]} onSelect={(a, b) => setSel([a, b])} />
          {sel && (
            <div className="mt-4 rounded-xl bg-white/[0.04] p-3 text-[13.5px] text-fg-muted">
              <span className="font-medium text-fg">{sel[0]}</span> × <span className="font-medium text-fg">{sel[1]}</span>:{" "}
              {pair
                ? `Pearson ${num(pair.pearson ?? NaN, 3)}, Spearman ${num(pair.spearman ?? NaN, 3)} over ${pair.n.toLocaleString()} rows (${strength(pair.spearman ?? pair.pearson ?? 0)}).`
                : (() => {
                    const i = corr.columns.indexOf(sel[0]);
                    const j = corr.columns.indexOf(sel[1]);
                    const v = corr[method][i]?.[j];
                    return v == null ? "not enough overlapping data." : `${method} ${v.toFixed(3)} (${strength(v)}).`;
                  })()}
            </div>
          )}
        </div>
      </Card>
      <div className="space-y-4">
        <Card>
          <CardHeader title="Strongest relationships" subtitle="Ranked by max(|r|, |ρ|)" />
          <div className="space-y-1 p-3">
            {corr.top_pairs.slice(0, 10).map((p) => {
              const v = (method === "spearman" ? p.spearman : p.pearson) ?? 0;
              return (
                <button key={`${p.a}-${p.b}`} onClick={() => setSel([p.a, p.b])} className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition hover:bg-white/[0.04]">
                  <div className="min-w-0 flex-1 text-[13px]">
                    <div className="truncate text-fg">{p.a}</div>
                    <div className="truncate text-fg-subtle">{p.b}</div>
                  </div>
                  <div className="w-24">
                    <div className="relative h-1.5 rounded-full bg-white/[0.06]">
                      <div className="absolute top-0 h-full rounded-full" style={{ left: v < 0 ? `${50 + v * 50}%` : "50%", width: `${Math.abs(v) * 50}%`, background: v < 0 ? "#fb7185" : "#8b7bff" }} />
                      <div className="absolute left-1/2 top-[-2px] h-[10px] w-px bg-white/20" />
                    </div>
                  </div>
                  <span className={cx("w-12 text-right font-mono text-[12.5px]", v < 0 ? "text-sev-critical" : "text-brand-300")}>{v.toFixed(2)}</span>
                </button>
              );
            })}
          </div>
        </Card>
        {mv && (
          <Card>
            <CardHeader title="Multivariate anomalies" subtitle={`Robust Mahalanobis over ${mv.columns.length} columns · ${mv.flagged.toLocaleString()} flagged`} icon={<Radar className="size-4" />} />
            <div className="space-y-2 p-4">
              {mv.rows.slice(0, 5).map((r) => (
                <div key={r.row} className="rounded-lg bg-white/[0.03] px-3 py-2 text-[12.5px]">
                  <div className="flex justify-between">
                    <span className="font-mono text-fg">row {r.row.toLocaleString()}</span>
                    <span className="font-mono text-sev-warning">d = {num(r.distance)}</span>
                  </div>
                  <div className="mt-1 text-fg-subtle">driven by {r.drivers.join(", ")}</div>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

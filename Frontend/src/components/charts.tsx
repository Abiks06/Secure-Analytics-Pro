import { useId, useMemo } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { compact, dateLabel, num, pct } from "../lib/format";
import type { BarChart as BarSpec, BoxChart, ChartSpec, HistogramChart, LineChart, ParetoChart, ScatterChart as ScatterSpec } from "../lib/types";

export const PALETTE = ["#8b7bff", "#22d3ee", "#34d399", "#fbbf24", "#fb7185", "#60a5fa", "#f472b6", "#a3e635"];
const AXIS = { stroke: "#6e7593", fontSize: 11, tickLine: false, axisLine: false } as const;
const GRID = { stroke: "rgba(255,255,255,0.06)", strokeDasharray: "3 4", vertical: false } as const;

function TooltipBox({ active, payload, label, fmtLabel }: { active?: boolean; payload?: { name?: string; value?: number | number[]; color?: string; payload?: Record<string, unknown> }[]; label?: string | number; fmtLabel?: (l: string | number) => string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="glass-strong rounded-lg px-3 py-2 text-xs shadow-2xl">
      {label != null && <div className="mb-1 font-medium text-fg">{fmtLabel ? fmtLabel(label) : String(label)}</div>}
      {payload
        .filter((p) => p.value != null && p.name !== "band")
        .map((p, i) => (
          <div key={i} className="flex items-center gap-2 text-fg-muted">
            <span className="size-2 rounded-full" style={{ background: p.color ?? "#8b7bff" }} />
            <span>{p.name}</span>
            <span className="ml-auto pl-3 font-mono text-fg tabular">{Array.isArray(p.value) ? p.value.map((v) => num(v)).join(" – ") : num(p.value as number)}</span>
          </div>
        ))}
    </div>
  );
}

function Gradient({ id, color }: { id: string; color: string }) {
  return (
    <defs>
      <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={color} stopOpacity={0.45} />
        <stop offset="100%" stopColor={color} stopOpacity={0} />
      </linearGradient>
    </defs>
  );
}

export function TrendChart({ spec, height = 240, granularity, color = "#8b7bff", showForecast = true }: { spec: Pick<LineChart, "t" | "y" | "forecast" | "anomalies" | "series">; height?: number; granularity?: string; color?: string; showForecast?: boolean }) {
  const gid = useId().replace(/:/g, "");
  const data = useMemo(() => {
    const rows: Record<string, unknown>[] = spec.t.map((t, i) => ({ t, actual: spec.y[i] }));
    if (showForecast && spec.forecast) {
      const last = rows.findLast((r) => r.actual != null);
      if (last) {
        last.forecast = last.actual;
        last.band = [last.actual, last.actual];
      }
      spec.forecast.t.forEach((t, i) =>
        rows.push({ t, forecast: spec.forecast!.y[i], band: [spec.forecast!.lower[i], spec.forecast!.upper[i]] }),
      );
    }
    return rows;
  }, [spec, showForecast]);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 10, right: 8, bottom: 0, left: -8 }}>
        <Gradient id={gid} color={color} />
        <CartesianGrid {...GRID} />
        <XAxis dataKey="t" {...AXIS} tickFormatter={(v) => dateLabel(String(v), granularity)} minTickGap={28} />
        <YAxis {...AXIS} tickFormatter={(v) => compact(v)} width={52} />
        <Tooltip content={<TooltipBox fmtLabel={(l) => dateLabel(String(l), granularity)} />} cursor={{ stroke: "rgba(255,255,255,0.15)" }} />
        {showForecast && spec.forecast && (
          <Area dataKey="band" name="band" stroke="none" fill={color} fillOpacity={0.12} isAnimationActive={false} />
        )}
        <Area dataKey="actual" name={spec.series} stroke={color} strokeWidth={2.2} fill={`url(#${gid})`} dot={false} activeDot={{ r: 4, strokeWidth: 0 }} connectNulls />
        {showForecast && spec.forecast && (
          <Line dataKey="forecast" name="Forecast" stroke={color} strokeDasharray="5 5" strokeWidth={2} dot={false} />
        )}
        {spec.anomalies?.map((a) => (
          <ReferenceDot key={a.t} x={a.t} y={a.value} r={6} fill="#fb7185" stroke="#05060a" strokeWidth={2} />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function ScatterView({ spec, height }: { spec: ScatterSpec; height: number }) {
  const pts = useMemo(() => spec.points.filter((p) => p[0] != null && p[1] != null).map(([x, y]) => ({ x, y })), [spec]);
  const xs = pts.map((p) => p.x);
  const [lo, hi] = [Math.min(...xs), Math.max(...xs)];
  const fit = [
    { x: lo, y: spec.fit.intercept + spec.fit.slope * lo },
    { x: hi, y: spec.fit.intercept + spec.fit.slope * hi },
  ];
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ top: 10, right: 10, bottom: 4, left: -8 }}>
        <CartesianGrid {...GRID} vertical />
        <XAxis type="number" dataKey="x" name={spec.x} {...AXIS} tickFormatter={(v) => compact(v)} domain={["auto", "auto"]} />
        <YAxis type="number" dataKey="y" name={spec.y} {...AXIS} tickFormatter={(v) => compact(v)} width={52} domain={["auto", "auto"]} />
        <Tooltip content={<TooltipBox />} cursor={{ strokeDasharray: "3 3" }} />
        <Scatter data={pts} fill="#8b7bff" fillOpacity={0.55} shape="circle" isAnimationActive={false} />
        <Scatter data={fit} line={{ stroke: "#22d3ee", strokeWidth: 2 }} shape={() => <g />} legendType="none" isAnimationActive={false} />
      </ScatterChart>
    </ResponsiveContainer>
  );
}

function BarView({ spec, height }: { spec: BarSpec; height: number }) {
  const data = spec.categories.map((c, i) => ({ name: String(c ?? "∅"), value: spec.values[i] }));
  const max = Math.max(...data.map((d) => d.value ?? 0));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 10, right: 8, bottom: 0, left: -8 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="name" {...AXIS} interval={0} tickFormatter={(v: string) => (v.length > 12 ? `${v.slice(0, 11)}…` : v)} />
        <YAxis {...AXIS} tickFormatter={(v) => compact(v)} width={52} />
        <Tooltip content={<TooltipBox />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
        {spec.baseline != null && <ReferenceLine y={spec.baseline} stroke="#fbbf24" strokeDasharray="4 4" label={{ value: "avg", fill: "#fbbf24", fontSize: 10, position: "right" }} />}
        <Bar dataKey="value" name={spec.y ?? "count"} radius={[6, 6, 2, 2]} maxBarSize={44}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.value === max ? "#22d3ee" : "#8b7bff"} fillOpacity={d.value === max ? 0.95 : 0.7} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function HistogramView({ bins, counts, height = 200, color = "#8b7bff" }: Omit<HistogramChart, "type" | "column"> & { height?: number; color?: string }) {
  const data = counts.map((c, i) => ({ name: `${num(bins[i])} – ${num(bins[i + 1])}`, x: bins[i], count: c }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 6, right: 4, bottom: 0, left: -12 }} barCategoryGap={1}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="x" {...AXIS} tickFormatter={(v) => compact(v)} minTickGap={20} />
        <YAxis {...AXIS} tickFormatter={(v) => compact(v)} width={44} />
        <Tooltip content={<TooltipBox fmtLabel={(l) => `from ${num(Number(l))}`} />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
        <Bar dataKey="count" name="rows" fill={color} fillOpacity={0.75} radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function ParetoView({ spec, height }: { spec: ParetoChart; height: number }) {
  const gid = useId().replace(/:/g, "");
  const data = spec.x.map((x, i) => ({ x, y: spec.y[i] }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 10, right: 8, bottom: 0, left: -8 }}>
        <Gradient id={gid} color="#34d399" />
        <CartesianGrid {...GRID} />
        <XAxis dataKey="x" type="number" domain={[0, 1]} {...AXIS} tickFormatter={(v) => pct(v)} />
        <YAxis domain={[0, 1]} {...AXIS} tickFormatter={(v) => pct(v)} width={44} />
        <Tooltip content={<TooltipBox fmtLabel={(l) => `Top ${pct(Number(l))} of rows`} />} />
        <ReferenceLine x={0.2} stroke="#fbbf24" strokeDasharray="4 4" />
        <Area dataKey="y" name="Share of total" stroke="#34d399" strokeWidth={2.2} fill={`url(#${gid})`} type="monotone" />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function BoxPlot({ spec, height = 120 }: { spec: BoxChart; height?: number }) {
  const lo = Math.min(spec.whisker_low, ...spec.samples.slice(-3));
  const hi = Math.max(spec.whisker_high, ...spec.samples.slice(0, 3));
  const useLog = spec.log_scale && lo > 0;
  const f = (v: number) => (useLog ? Math.log10(v) : v);
  const [a, b] = [f(lo), f(hi)];
  const x = (v: number) => 4 + ((f(v) - a) / (b - a || 1)) * 92;
  const mid = height / 2;
  return (
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="w-full" style={{ height }}>
      <line x1={x(spec.whisker_low)} x2={x(spec.whisker_high)} y1={mid} y2={mid} stroke="#6e7593" strokeWidth={0.4} vectorEffect="non-scaling-stroke" />
      {[spec.whisker_low, spec.whisker_high].map((w, i) => (
        <line key={i} x1={x(w)} x2={x(w)} y1={mid - 12} y2={mid + 12} stroke="#6e7593" vectorEffect="non-scaling-stroke" />
      ))}
      <rect x={x(spec.q1)} width={Math.max(0.5, x(spec.q3) - x(spec.q1))} y={mid - 22} height={44} rx={1.5} fill="rgba(139,123,255,0.25)" stroke="#8b7bff" vectorEffect="non-scaling-stroke" />
      <line x1={x(spec.median)} x2={x(spec.median)} y1={mid - 22} y2={mid + 22} stroke="#22d3ee" strokeWidth={2} vectorEffect="non-scaling-stroke" />
      {spec.samples.map((s, i) => (
        <circle key={i} cx={x(s)} cy={mid + ((i % 5) - 2) * 6} r={1.1} fill="#fb7185" />
      ))}
    </svg>
  );
}

export function InsightChart({ spec, height = 200 }: { spec: ChartSpec; height?: number }) {
  switch (spec.type) {
    case "scatter":
      return <ScatterView spec={spec} height={height} />;
    case "bar":
      return <BarView spec={spec} height={height} />;
    case "line":
      return <TrendChart spec={spec} height={height} />;
    case "box":
      return (
        <div>
          <BoxPlot spec={spec} height={Math.min(height, 110)} />
          <div className="mt-2 flex justify-between font-mono text-[11px] text-fg-subtle">
            <span>Q1 {num(spec.q1)}</span>
            <span className="text-cyan-glow">median {num(spec.median)}</span>
            <span>Q3 {num(spec.q3)}</span>
            <span className="text-sev-critical">max {num(spec.samples[0])}</span>
          </div>
        </div>
      );
    case "histogram":
      return <HistogramView bins={spec.bins} counts={spec.counts} height={height} />;
    case "pareto":
      return <ParetoView spec={spec} height={height} />;
    default:
      return null;
  }
}

export function MiniBars({ values, color = "#8b7bff", height = 36 }: { values: number[]; color?: string; height?: number }) {
  const max = Math.max(1, ...values);
  return (
    <div className="flex items-end gap-[2px]" style={{ height }}>
      {values.map((v, i) => (
        <div key={i} className="flex-1 rounded-t-[2px]" style={{ height: `${Math.max(4, (v / max) * 100)}%`, background: color, opacity: 0.35 + 0.65 * (v / max) }} />
      ))}
    </div>
  );
}

function corrColor(v: number | null): string {
  if (v == null) return "rgba(255,255,255,0.03)";
  const a = Math.min(1, Math.abs(v));
  return v >= 0 ? `rgba(139,123,255,${0.08 + a * 0.85})` : `rgba(251,113,133,${0.08 + a * 0.85})`;
}

export function Heatmap({ labels, matrix, onSelect }: { labels: string[]; matrix: (number | null)[][]; onSelect?: (a: string, b: string) => void }) {
  const n = labels.length;
  return (
    <div className="overflow-x-auto">
      <div className="inline-grid min-w-full gap-[3px]" style={{ gridTemplateColumns: `minmax(110px,160px) repeat(${n}, minmax(34px, 1fr))` }}>
        <div />
        {labels.map((l) => (
          <div key={l} className="flex h-24 items-end justify-center pb-1">
            <span className="origin-bottom-left translate-x-3 -rotate-45 whitespace-nowrap text-[11px] text-fg-subtle">{l.length > 16 ? `${l.slice(0, 15)}…` : l}</span>
          </div>
        ))}
        {labels.map((row, i) => (
          <div key={row} className="contents">
            <div className="flex items-center justify-end truncate pr-2 text-[12px] text-fg-muted" title={row}>
              {row}
            </div>
            {labels.map((col, j) => {
              const v = matrix[i][j];
              return (
                <button
                  key={col}
                  title={`${row} × ${col}: ${v == null ? "n/a" : v.toFixed(3)}`}
                  onClick={() => i !== j && onSelect?.(row, col)}
                  className="group relative grid aspect-square place-items-center rounded-[5px] font-mono text-[10px] transition-transform hover:z-10 hover:scale-110 hover:ring-1 hover:ring-white/40"
                  style={{ background: corrColor(v) }}
                >
                  <span className={Math.abs(v ?? 0) > 0.45 ? "text-white" : "text-fg-subtle opacity-0 group-hover:opacity-100"}>{v == null ? "" : v.toFixed(2).replace("0.", ".")}</span>
                </button>
              );
            })}
          </div>
        ))}
      </div>
      <div className="mt-4 flex items-center gap-3 text-[11px] text-fg-subtle">
        <span>−1</span>
        <div className="h-2 w-48 rounded-full" style={{ background: "linear-gradient(90deg, rgba(251,113,133,0.95), rgba(255,255,255,0.05), rgba(139,123,255,0.95))" }} />
        <span>+1</span>
      </div>
    </div>
  );
}

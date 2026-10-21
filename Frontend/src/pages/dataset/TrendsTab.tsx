import { ArrowDownRight, ArrowUpRight, CalendarRange, Minus, Repeat, TrendingUp } from "lucide-react";
import { useState } from "react";
import { PALETTE, TrendChart } from "../../components/charts";
import { Badge, Card, CardHeader, cx, Empty } from "../../components/ui";
import { dateLabel, pct, withUnit } from "../../lib/format";
import type { Report } from "../../lib/types";

export default function TrendsTab({ report }: { report: Report }) {
  const ts = report.timeseries;
  const [active, setActive] = useState(0);
  const [forecast, setForecast] = useState(true);
  if (!ts) {
    return (
      <Card>
        <Empty icon={<CalendarRange className="size-5" />} title="No time dimension found" body="Trend analysis needs a date or timestamp column with at least 8 distinct values spanning 6+ periods." />
      </Card>
    );
  }
  const s = ts.series[active];
  const color = PALETTE[active % PALETTE.length];
  const tr = s.trend;
  const Arrow = tr.direction === "up" ? ArrowUpRight : tr.direction === "down" ? ArrowDownRight : Minus;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
        {ts.series.map((x, i) => {
          const up = x.trend.direction === "up";
          return (
            <button
              key={x.name}
              onClick={() => setActive(i)}
              className={cx("glass rounded-xl2 p-4 text-left transition", i === active ? "border-white/20 ring-1 ring-white/10" : "opacity-75 hover:opacity-100")}
            >
              <div className="flex items-center gap-2 text-[12px] text-fg-subtle">
                <span className="size-2 rounded-full" style={{ background: PALETTE[i % PALETTE.length] }} />
                <span className="truncate">{x.name === "Records" ? "Row count" : `${x.method} of ${x.name}`}</span>
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="font-mono text-xl font-semibold">{withUnit(x.trend.to, x.unit)}</span>
                {x.trend.change_pct != null && (
                  <span className={cx("font-mono text-[12px]", x.trend.significant ? (up ? "text-mint" : "text-sev-critical") : "text-fg-subtle")}>
                    {up ? "+" : ""}
                    {pct(x.trend.change_pct, 1)}
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>

      <Card>
        <CardHeader
          title={`${s.name === "Records" ? "Row count" : `${s.method} of ${s.name}`} per ${ts.granularity.replace("1", "")}`}
          subtitle={`${ts.time_column} · ${dateLabel(ts.start)} → ${dateLabel(ts.end)}${ts.partial_last ? " · last period is partial" : ""}`}
          icon={<TrendingUp className="size-4" />}
          action={
            <label className="flex cursor-pointer items-center gap-2 text-[12.5px] text-fg-muted">
              <input type="checkbox" checked={forecast} onChange={(e) => setForecast(e.target.checked)} className="accent-brand-500" />
              Forecast
            </label>
          }
        />
        <div className="px-3 pb-4 pt-3">
          <TrendChart spec={{ t: ts.t, y: s.y, forecast: s.forecast, anomalies: s.anomalies, series: s.name }} height={340} granularity={ts.granularity} color={color} showForecast={forecast} />
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="p-5">
          <div className="text-[12px] uppercase tracking-[0.1em] text-fg-subtle">Trend</div>
          <div className={cx("mt-2 flex items-center gap-2 text-xl font-semibold", tr.significant ? (tr.direction === "up" ? "text-mint" : "text-sev-critical") : "text-fg")}>
            <Arrow className="size-5" /> {tr.significant ? `Significant ${tr.direction}trend` : "No significant trend"}
          </div>
          <p className="mt-2 text-[13px] text-fg-muted">
            Mann-Kendall z = {tr.mk_z.toFixed(2)}, p = {tr.p_value < 0.001 ? "< 0.001" : tr.p_value.toFixed(3)}. Average of the first periods{" "}
            {withUnit(tr.from, s.unit)} → last {withUnit(tr.to, s.unit)}.
          </p>
        </Card>
        <Card className="p-5">
          <div className="text-[12px] uppercase tracking-[0.1em] text-fg-subtle">Forecast</div>
          {s.forecast ? (
            <>
              <div className="mt-2 font-mono text-xl font-semibold" style={{ color }}>
                {withUnit(s.forecast.y[s.forecast.y.length - 1], s.unit)}
              </div>
              <p className="mt-2 text-[13px] text-fg-muted">
                Expected by {dateLabel(s.forecast.t[s.forecast.t.length - 1], ts.granularity)} (95% interval {withUnit(s.forecast.lower[s.forecast.lower.length - 1], s.unit)} –{" "}
                {withUnit(s.forecast.upper[s.forecast.upper.length - 1], s.unit)}). Holt α={s.forecast.alpha}, β={s.forecast.beta}.
              </p>
            </>
          ) : (
            <p className="mt-2 text-[13px] text-fg-muted">Not enough periods to forecast.</p>
          )}
        </Card>
        <Card className="p-5">
          <div className="text-[12px] uppercase tracking-[0.1em] text-fg-subtle">Anomalies & seasonality</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {s.anomalies.length === 0 && <Badge>No anomalous periods</Badge>}
            {s.anomalies.map((a) => (
              <Badge key={a.t} tone={a.value > a.expected ? "warning" : "critical"}>
                {dateLabel(a.t, ts.granularity)}: {withUnit(a.value, s.unit)}
              </Badge>
            ))}
          </div>
          <p className="mt-3 flex items-center gap-2 text-[13px] text-fg-muted">
            <Repeat className="size-3.5" />
            {s.seasonality.detected ? `Seasonal cycle every ${s.seasonality.lag} periods (ACF ${s.seasonality.acf?.toFixed(2)})` : "No strong seasonal cycle detected"}
          </p>
        </Card>
      </div>
    </div>
  );
}

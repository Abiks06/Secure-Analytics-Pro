import { Lightbulb } from "lucide-react";
import { useMemo, useState } from "react";
import { InsightCard } from "../../components/InsightCard";
import { Card, cx, Empty } from "../../components/ui";
import { severityStyle } from "../../lib/format";
import type { Report, Severity } from "../../lib/types";

export default function InsightsTab({ report }: { report: Report }) {
  const [kind, setKind] = useState<string>("all");
  const [sev, setSev] = useState<Severity | "all">("all");
  const kinds = useMemo(() => {
    const m = new Map<string, number>();
    report.insights.forEach((i) => m.set(i.kind, (m.get(i.kind) ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [report]);
  const list = report.insights.filter((i) => (kind === "all" || i.kind === kind) && (sev === "all" || i.severity === sev));
  const chip = (active: boolean) =>
    cx("h-8 rounded-full border px-3 text-[12.5px] font-medium capitalize transition", active ? "border-brand-400/50 bg-brand-500/15 text-fg" : "border-white/10 text-fg-subtle hover:border-white/20 hover:text-fg-muted");
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <button className={chip(kind === "all")} onClick={() => setKind("all")}>
          All <span className="ml-1 font-mono text-[11px] opacity-70">{report.insights.length}</span>
        </button>
        {kinds.map(([k, n]) => (
          <button key={k} className={chip(kind === k)} onClick={() => setKind(k)}>
            {k} <span className="ml-1 font-mono text-[11px] opacity-70">{n}</span>
          </button>
        ))}
        <div className="mx-1 h-5 w-px bg-white/10" />
        {(["all", "critical", "warning", "notable", "positive", "info"] as const).map((s) => (
          <button key={s} className={chip(sev === s)} onClick={() => setSev(s)}>
            {s !== "all" && <span className={cx("mr-1.5 inline-block size-1.5 rounded-full", severityStyle[s].dot)} />}
            {s}
          </button>
        ))}
      </div>
      {list.length === 0 ? (
        <Card>
          <Empty icon={<Lightbulb className="size-5" />} title="No insights match these filters" />
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
          {list.map((ins, i) => (
            <InsightCard key={ins.id} insight={ins} i={i} />
          ))}
        </div>
      )}
    </div>
  );
}

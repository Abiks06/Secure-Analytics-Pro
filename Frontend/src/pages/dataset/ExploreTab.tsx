import { useMutation, useQuery } from "@tanstack/react-query";
import { Bot, CornerDownLeft, Play, Sparkles, Terminal, Wand2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Button, Card, CardHeader, cx, Kbd } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { compact, ms, num, prettyType } from "../../lib/format";
import type { AskResult, DatasetSummary, QueryResult, Report } from "../../lib/types";

const NUMERIC_TYPE = /Int|Float|Decimal|UInt/;

function ResultChart({ result, hint }: { result: QueryResult; hint?: AskResult["chart"] }) {
  const cols = result.columns;
  if (result.rows.length < 2 || cols.length < 2) return null;
  const xIdx = hint?.x ? cols.findIndex((c) => c.name === hint.x) : cols.findIndex((c) => !NUMERIC_TYPE.test(c.type));
  const yIdx = hint?.y ? cols.findIndex((c) => c.name === hint.y) : cols.findIndex((c, i) => i !== xIdx && NUMERIC_TYPE.test(c.type));
  if (xIdx < 0 || yIdx < 0 || !NUMERIC_TYPE.test(cols[yIdx].type)) return null;
  const data = result.rows.slice(0, 60).map((r) => ({ x: String(r[xIdx]), y: Number(r[yIdx]) }));
  const isTime = hint?.type === "line" || /Date|Datetime/.test(cols[xIdx].type);
  const common = (
    <>
      <CartesianGrid stroke="rgba(255,255,255,0.06)" strokeDasharray="3 4" vertical={false} />
      <XAxis dataKey="x" stroke="#6e7593" fontSize={11} tickLine={false} axisLine={false} tickFormatter={(v: string) => (isTime ? v.slice(0, 10) : v.length > 12 ? `${v.slice(0, 11)}…` : v)} minTickGap={16} />
      <YAxis stroke="#6e7593" fontSize={11} tickLine={false} axisLine={false} tickFormatter={(v) => compact(v)} width={52} />
      <Tooltip contentStyle={{ background: "#121624", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 10, fontSize: 12 }} formatter={(v) => num(Number(v))} />
    </>
  );
  return (
    <div className="h-64 px-2">
      <ResponsiveContainer width="100%" height="100%">
        {isTime ? (
          <LineChart data={data} margin={{ top: 10, right: 10, left: -6, bottom: 0 }}>
            {common}
            <Line dataKey="y" name={cols[yIdx].name} stroke="#22d3ee" strokeWidth={2.2} dot={false} />
          </LineChart>
        ) : (
          <BarChart data={data} margin={{ top: 10, right: 10, left: -6, bottom: 0 }}>
            {common}
            <Bar dataKey="y" name={cols[yIdx].name} fill="#8b7bff" radius={[6, 6, 2, 2]} maxBarSize={40} />
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

export function ResultTable({ result, max = 200 }: { result: QueryResult; max?: number }) {
  return (
    <div className="max-h-[420px] overflow-auto rounded-xl border border-white/[0.07]">
      <table className="w-full border-collapse text-[13px]">
        <thead className="sticky top-0 z-10 bg-ink-850">
          <tr>
            {result.columns.map((c) => (
              <th key={c.name} className="whitespace-nowrap border-b border-white/[0.08] px-3 py-2 text-left font-medium text-fg-muted">
                {c.name}
                <span className="ml-1.5 font-mono text-[10px] font-normal text-fg-subtle">{prettyType(c.type)}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.slice(0, max).map((r, i) => (
            <tr key={i} className="odd:bg-white/[0.015] hover:bg-white/[0.04]">
              {r.map((v, j) => (
                <td key={j} className={cx("max-w-[280px] truncate whitespace-nowrap px-3 py-1.5", typeof v === "number" ? "text-right font-mono tabular" : "text-fg-muted")}>
                  {v == null ? <span className="text-fg-subtle/60">null</span> : typeof v === "number" ? num(v) : String(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function suggestions(report: Report): { q: string; sql: string }[] {
  const num_ = report.columns.filter((c) => c.kind === "numeric").map((c) => c.name);
  const cat = report.columns.filter((c) => c.kind === "categorical" && c.distinct <= 30).map((c) => c.name);
  const time = report.timeseries?.time_column;
  const out: { q: string; sql: string }[] = [];
  const target =
    ["revenue", "sales", "amount", "total", "spend", "profit", "price"]
      .map((p) => num_.find((n) => n.toLowerCase().includes(p)))
      .find(Boolean) ?? num_[0];
  if (cat[0] && target)
    out.push({
      q: `Which ${cat[0]} has the highest average ${target}?`,
      sql: `SELECT "${cat[0]}", round(avg("${target}"), 2) AS avg_${target.replace(/\W+/g, "_").toLowerCase()}, count(*) AS rows\nFROM data\nGROUP BY 1\nORDER BY 2 DESC`,
    });
  if (time && target)
    out.push({
      q: `How has total ${target} changed month by month?`,
      sql: `SELECT date_trunc('month', "${time}") AS month, round(sum("${target}"), 2) AS total\nFROM data\nGROUP BY 1\nORDER BY 1`,
    });
  if (cat[1] && cat[0])
    out.push({
      q: `Break down rows by ${cat[0]} and ${cat[1]}`,
      sql: `SELECT "${cat[0]}", "${cat[1]}", count(*) AS n\nFROM data\nGROUP BY ALL\nORDER BY n DESC\nLIMIT 25`,
    });
  if (target) out.push({ q: `What are the 10 largest ${target} values?`, sql: `SELECT *\nFROM data\nORDER BY "${target}" DESC NULLS LAST\nLIMIT 10` });
  return out.slice(0, 4);
}

export default function ExploreTab({ ds, report }: { ds: DatasetSummary; report: Report }) {
  const system = useQuery({ queryKey: ["system"], queryFn: api.system });
  const sugg = useMemo(() => suggestions(report), [report]);
  const [sql, setSql] = useState(sugg[0]?.sql ?? "SELECT *\nFROM data\nLIMIT 100");
  const [question, setQuestion] = useState("");
  const editor = useRef<HTMLTextAreaElement>(null);

  const run = useMutation({ mutationFn: (s: string) => api.query(ds.id, s) });
  const ask = useMutation({ mutationFn: (q: string) => api.ask(ds.id, q) });
  const aiOn = !!system.data?.ai_enabled;

  const submitAsk = (q: string) => {
    if (q.trim().length < 3) return;
    setQuestion(q);
    ask.mutate(q.trim());
  };

  return (
    <div className="space-y-4">
      <Card className="ring-gradient relative overflow-hidden">
        <div className="pointer-events-none absolute -left-24 -top-24 size-72 rounded-full bg-brand-500/15 blur-3xl" />
        <CardHeader
          title="Ask your data"
          subtitle={aiOn ? `Claude writes the SQL, the sandbox runs it. Only the schema, statistics and masked results leave the server.` : "Set ANTHROPIC_API_KEY on the server to enable natural-language questions."}
          icon={<Bot className="size-4" />}
          action={aiOn ? <Badge tone="positive">online</Badge> : <Badge>offline</Badge>}
        />
        <div className="p-5">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submitAsk(question);
            }}
            className="flex gap-2"
          >
            <div className="relative flex-1">
              <Sparkles className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-brand-300" />
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                disabled={!aiOn}
                placeholder={sugg[0]?.q ?? "What would you like to know?"}
                className="h-12 w-full rounded-xl border border-white/10 bg-ink-900/80 pl-10 pr-4 text-[15px] outline-none transition placeholder:text-fg-subtle focus:border-brand-400/60 focus:ring-4 focus:ring-brand-500/15 disabled:opacity-50"
              />
            </div>
            <Button type="submit" variant="primary" size="lg" loading={ask.isPending} disabled={!aiOn} icon={<CornerDownLeft className="size-4" />}>
              Ask
            </Button>
          </form>
          <div className="mt-3 flex flex-wrap gap-2">
            {sugg.map((s) => (
              <button key={s.q} disabled={!aiOn} onClick={() => submitAsk(s.q)} className="rounded-full border border-white/10 px-3 py-1 text-[12.5px] text-fg-muted transition hover:border-brand-400/40 hover:text-fg disabled:opacity-50">
                {s.q}
              </button>
            ))}
          </div>
          <AnimatePresence mode="wait">
            {ask.isPending && (
              <motion.div key="thinking" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="mt-5 space-y-2">
                <div className="skeleton h-5 w-3/4 rounded-md" />
                <div className="skeleton h-5 w-1/2 rounded-md" />
              </motion.div>
            )}
            {ask.isError && (
              <motion.p key="err" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-5 text-sm text-sev-critical">
                {ask.error instanceof ApiError ? ask.error.message : "Something went wrong."}
              </motion.p>
            )}
            {ask.data && !ask.isPending && (
              <motion.div key={ask.data.question} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="mt-5 space-y-4">
                {ask.data.answer ? (
                  <p className="text-[16px] leading-relaxed text-fg">{ask.data.answer}</p>
                ) : (
                  <p className="text-sm text-sev-critical">{ask.data.error}</p>
                )}
                {ask.data.result && <ResultChart result={ask.data.result} hint={ask.data.chart} />}
                {ask.data.sql && (
                  <div className="rounded-xl border border-white/[0.07] bg-ink-900/70">
                    <div className="flex items-center justify-between border-b border-white/[0.06] px-3 py-2 text-[12px] text-fg-subtle">
                      <span>{ask.data.rationale ?? "Generated SQL"}</span>
                      <button
                        className="flex items-center gap-1 text-brand-300 hover:text-brand-400"
                        onClick={() => {
                          setSql(ask.data!.sql!);
                          editor.current?.scrollIntoView({ behavior: "smooth", block: "center" });
                        }}
                      >
                        <Wand2 className="size-3" /> Open in editor
                      </button>
                    </div>
                    <pre className="overflow-x-auto p-3 font-mono text-[12.5px] leading-relaxed text-cyan-glow/90">{ask.data.sql}</pre>
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </Card>

      <Card>
        <CardHeader
          title="SQL sandbox"
          subtitle={`DuckDB over the privacy-filtered table "data" · read-only · ${system.data?.query_timeout_s ?? 10}s / ${compact(system.data?.query_row_limit ?? 5000)} row limit`}
          icon={<Terminal className="size-4" />}
          action={
            <Button variant="primary" size="sm" icon={<Play className="size-3.5" />} loading={run.isPending} onClick={() => run.mutate(sql)}>
              Run
            </Button>
          }
        />
        <div className="space-y-4 p-5">
          <div className="relative overflow-hidden rounded-xl border border-white/[0.08] bg-ink-900/80 focus-within:border-brand-400/50">
            <textarea
              ref={editor}
              value={sql}
              onChange={(e) => setSql(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  run.mutate(sql);
                }
              }}
              spellCheck={false}
              rows={Math.min(14, Math.max(5, sql.split("\n").length + 1))}
              className="block w-full resize-y bg-transparent p-4 font-mono text-[13px] leading-relaxed text-fg outline-none"
            />
            <div className="pointer-events-none absolute bottom-2 right-3 flex items-center gap-1 text-[11px] text-fg-subtle">
              <Kbd>Ctrl</Kbd> + <Kbd>Enter</Kbd>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {sugg.map((s) => (
              <button key={s.sql} onClick={() => setSql(s.sql)} className="rounded-lg bg-white/[0.04] px-2.5 py-1 font-mono text-[11.5px] text-fg-subtle transition hover:bg-white/[0.07] hover:text-fg-muted">
                {s.q}
              </button>
            ))}
          </div>
          {run.isError && (
            <div className="rounded-xl border border-sev-critical/25 bg-sev-critical/10 px-3.5 py-2.5 font-mono text-[12.5px] text-sev-critical">
              {run.error instanceof ApiError ? run.error.message : "Query failed"}
            </div>
          )}
          {run.data && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-fg-subtle">
                <Badge tone="positive">{run.data.row_count.toLocaleString()} rows</Badge>
                <Badge>{ms(run.data.elapsed_ms)}</Badge>
                {run.data.truncated && <Badge tone="warning">truncated</Badge>}
              </div>
              <ResultChart result={run.data} />
              <ResultTable result={run.data} />
            </motion.div>
          )}
        </div>
      </Card>
    </div>
  );
}

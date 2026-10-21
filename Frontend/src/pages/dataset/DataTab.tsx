import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Lock, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Button, Card, cx, Input, Skeleton } from "../../components/ui";
import { api } from "../../lib/api";
import { num, prettyType } from "../../lib/format";
import type { DatasetSummary } from "../../lib/types";

const PAGE = 50;

export default function DataTab({ ds }: { ds: DatasetSummary }) {
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState<{ col: string; desc: boolean } | null>(null);
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(search);
      setOffset(0);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const { data, isFetching, isLoading } = useQuery({
    queryKey: ["rows", ds.id, offset, sort, q, ds.privacy_policy],
    queryFn: () => api.rows(ds.id, { offset, limit: PAGE, sort: sort?.col, desc: sort?.desc, q }),
    placeholderData: keepPreviousData,
  });
  const protectedCols = new Set(Object.keys(ds.privacy_policy));

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-white/[0.06] p-4">
        <div className="w-full sm:w-72">
          <Input icon={<Search className="size-4" />} placeholder="Search text columns" value={search} onChange={(e) => setSearch(e.target.value)} className="h-9 text-sm" />
        </div>
        {protectedCols.size > 0 && (
          <Badge tone="positive">
            <Lock className="size-3" /> {protectedCols.size} columns privacy-protected
          </Badge>
        )}
        <div className="ml-auto flex items-center gap-2 text-[13px] text-fg-subtle">
          {data && (
            <span className="font-mono">
              {data.total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total.toLocaleString()}
            </span>
          )}
          <Button size="sm" variant="ghost" aria-label="Previous page" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - PAGE))}>
            <ChevronLeft className="size-4" />
          </Button>
          <Button size="sm" variant="ghost" aria-label="Next page" disabled={!data || offset + PAGE >= data.total} onClick={() => setOffset((o) => o + PAGE)}>
            <ChevronRight className="size-4" />
          </Button>
        </div>
      </div>
      {isLoading || !data ? (
        <div className="space-y-2 p-4">
          {Array.from({ length: 10 }).map((_, i) => (
            <Skeleton key={i} className="h-7" />
          ))}
        </div>
      ) : (
        <div className={cx("max-h-[640px] overflow-auto transition-opacity", isFetching && "opacity-60")}>
          <table className="w-full border-collapse text-[13px]">
            <thead className="sticky top-0 z-10 bg-ink-850">
              <tr>
                <th className="sticky left-0 z-10 w-14 border-b border-white/[0.08] bg-ink-850 px-3 py-2.5 text-right font-mono text-[11px] font-normal text-fg-subtle">#</th>
                {data.columns.map((c) => {
                  const active = sort?.col === c.name;
                  return (
                    <th key={c.name} className="whitespace-nowrap border-b border-white/[0.08] px-3 py-2 text-left">
                      <button
                        onClick={() => {
                          setOffset(0);
                          setSort((s) => (s?.col === c.name ? (s.desc ? null : { col: c.name, desc: true }) : { col: c.name, desc: false }));
                        }}
                        className={cx("flex items-center gap-1 font-medium transition", active ? "text-fg" : "text-fg-muted hover:text-fg")}
                      >
                        {protectedCols.has(c.name) && <Lock className="size-3 text-mint" />}
                        {c.name}
                        {active && (sort!.desc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />)}
                      </button>
                      <div className="font-mono text-[10px] font-normal text-fg-subtle">{prettyType(c.type)}</div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r, i) => (
                <tr key={data.index[i]} className="odd:bg-white/[0.015] hover:bg-white/[0.04]">
                  <td className="sticky left-0 bg-ink-900/95 px-3 py-1.5 text-right font-mono text-[11px] text-fg-subtle">{data.index[i]}</td>
                  {r.map((v, j) => (
                    <td key={j} className={cx("max-w-[260px] truncate whitespace-nowrap px-3 py-1.5", typeof v === "number" ? "text-right font-mono tabular" : typeof v === "boolean" ? "font-mono" : "text-fg-muted")}>
                      {v == null ? (
                        <span className="text-fg-subtle/50">∅</span>
                      ) : typeof v === "boolean" ? (
                        <span className={v ? "text-mint" : "text-fg-subtle"}>{String(v)}</span>
                      ) : typeof v === "number" ? (
                        num(v)
                      ) : v === "[REDACTED]" ? (
                        <span className="rounded bg-sev-critical/10 px-1.5 py-0.5 font-mono text-[11px] text-sev-critical">REDACTED</span>
                      ) : (
                        String(v)
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

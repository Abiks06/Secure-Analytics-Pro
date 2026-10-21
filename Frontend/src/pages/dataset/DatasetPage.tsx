import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Columns3,
  Download,
  Fingerprint,
  GitCompareArrows,
  LayoutDashboard,
  Lightbulb,
  Lock,
  MoreHorizontal,
  Pencil,
  Sparkles,
  Table2,
  Trash2,
  TrendingUp,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { PIPELINE } from "../../components/UploadPanel";
import { Badge, Button, Card, cx, Empty, QualityRing, Skeleton, Tabs } from "../../components/ui";
import { api, ApiError, streamProgress } from "../../lib/api";
import { bytes, ms, qualityTone } from "../../lib/format";
import type { DatasetSummary, ProgressEvent, Report } from "../../lib/types";
import ColumnsTab from "./ColumnsTab";
import CorrelationsTab from "./CorrelationsTab";
import DataTab from "./DataTab";
import ExploreTab from "./ExploreTab";
import InsightsTab from "./InsightsTab";
import Overview from "./Overview";
import PrivacyTab from "./PrivacyTab";
import TrendsTab from "./TrendsTab";

type TabId = "overview" | "insights" | "columns" | "correlations" | "trends" | "privacy" | "explore" | "data";

function Processing({ ds }: { ds: DatasetSummary }) {
  const [event, setEvent] = useState<ProgressEvent | null>(null);
  const qc = useQueryClient();
  useEffect(() => {
    const ctrl = new AbortController();
    streamProgress(
      ds.id,
      (e) => {
        setEvent(e);
        if (e.status === "ready" || e.status === "failed") {
          qc.invalidateQueries({ queryKey: ["dataset", ds.id] });
          qc.invalidateQueries({ queryKey: ["datasets"] });
        }
      },
      ctrl.signal,
    ).catch(() => undefined);
    return () => ctrl.abort();
  }, [ds.id, qc]);
  const idx = PIPELINE.findIndex((s) => s.id === (event?.stage ?? ds.stage));
  return (
    <Card className="mx-auto max-w-xl p-8 text-center">
      <div className="mx-auto grid size-14 place-items-center rounded-2xl bg-brand-gradient text-white shadow-xl shadow-brand-600/30">
        <Lock className="size-6 animate-pulse" />
      </div>
      <h2 className="mt-5 text-xl font-semibold">Analysing {ds.name}</h2>
      <p className="mt-1 text-sm text-fg-muted">{event?.message ?? "Streaming progress from the engine…"}</p>
      <div className="mt-7 space-y-2 text-left">
        {PIPELINE.map((s, i) => (
          <div key={s.id} className="flex items-center gap-3 text-sm">
            <span className={cx("size-2 rounded-full", i < idx ? "bg-mint" : i === idx ? "animate-pulse bg-brand-400" : "bg-white/10")} />
            <span className={i <= idx ? "text-fg" : "text-fg-subtle"}>{s.label}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function ActionsMenu({ ds }: { ds: DatasetSummary }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const qc = useQueryClient();
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const del = useMutation({
    mutationFn: () => api.remove(ds.id),
    onSuccess: () => {
      toast.success("Dataset crypto-shredded", { description: "Key destroyed and ciphertext overwritten." });
      qc.invalidateQueries({ queryKey: ["datasets"] });
      qc.invalidateQueries({ queryKey: ["system"] });
      navigate("/app");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Delete failed"),
  });
  const rename = async () => {
    const name = window.prompt("Rename dataset", ds.name)?.trim();
    if (!name || name === ds.name) return;
    await api.rename(ds.id, name);
    qc.invalidateQueries({ queryKey: ["dataset", ds.id] });
    qc.invalidateQueries({ queryKey: ["datasets"] });
  };
  const exp = async (f: "csv" | "parquet" | "json") => {
    setOpen(false);
    const t = toast.loading(`Preparing ${f.toUpperCase()} export…`);
    try {
      await api.export(ds.id, f);
      toast.success("Export ready", { id: t, description: "Privacy policy applied. Logged to your audit trail." });
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Export failed", { id: t });
    }
  };
  return (
    <div className="relative" ref={ref}>
      <div className="flex gap-2">
        <Button variant="secondary" icon={<Download className="size-4" />} onClick={() => setOpen((o) => !o)}>
          Export
        </Button>
        <Button variant="ghost" className="!px-2.5" aria-label="More actions" onClick={() => setOpen((o) => !o)}>
          <MoreHorizontal className="size-4" />
        </Button>
      </div>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.97 }}
            transition={{ duration: 0.15 }}
            className="glass-strong absolute right-0 z-30 mt-2 w-60 origin-top-right rounded-xl p-1.5 shadow-2xl"
          >
            <div className="px-2.5 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Export cleaned data</div>
            {(["csv", "parquet", "json"] as const).map((f) => (
              <button key={f} onClick={() => exp(f)} className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-fg-muted hover:bg-white/[0.06] hover:text-fg">
                <Download className="size-3.5" /> {f.toUpperCase()}
              </button>
            ))}
            <div className="my-1 h-px bg-white/[0.07]" />
            <button onClick={rename} className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-fg-muted hover:bg-white/[0.06] hover:text-fg">
              <Pencil className="size-3.5" /> Rename
            </button>
            <button
              onClick={() => window.confirm(`Permanently delete “${ds.name}”? The encryption key will be destroyed.`) && del.mutate()}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-sev-critical hover:bg-sev-critical/10"
            >
              <Trash2 className="size-3.5" /> Delete & crypto-shred
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function DatasetPage() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as TabId) || "overview";
  const setTab = (t: TabId) => setParams(t === "overview" ? {} : { tab: t }, { replace: true });

  const meta = useQuery({ queryKey: ["dataset", id], queryFn: () => api.dataset(id) });
  const ready = meta.data?.status === "ready";
  const report = useQuery({ queryKey: ["report", id, meta.data?.updated_at], queryFn: () => api.report(id), enabled: ready, staleTime: Infinity });

  if (meta.isError) {
    return (
      <Card>
        <Empty icon={<Lock className="size-5" />} title="Dataset not found" body="It may have been deleted, or it belongs to another account." action={<Link to="/app"><Button>Back to workspace</Button></Link>} />
      </Card>
    );
  }
  const ds = meta.data;
  const r: Report | undefined = report.data?.report;
  const tone = qualityTone(ds?.quality_score);

  const tabs: { id: TabId; label: string; icon: React.ReactNode; badge?: React.ReactNode }[] = [
    { id: "overview", label: "Overview", icon: <LayoutDashboard className="size-4" /> },
    { id: "insights", label: "Insights", icon: <Lightbulb className="size-4" />, badge: r && <span className="font-mono text-[11px] text-fg-subtle">{r.insights.length}</span> },
    { id: "columns", label: "Columns", icon: <Columns3 className="size-4" /> },
    { id: "correlations", label: "Correlations", icon: <GitCompareArrows className="size-4" /> },
    { id: "trends", label: "Trends", icon: <TrendingUp className="size-4" /> },
    { id: "privacy", label: "Privacy", icon: <Fingerprint className="size-4" />, badge: r && r.privacy.findings.length > 0 && <span className="size-1.5 rounded-full bg-sev-critical" /> },
    { id: "explore", label: "Explore", icon: <Sparkles className="size-4" /> },
    { id: "data", label: "Data", icon: <Table2 className="size-4" /> },
  ];

  return (
    <div className="space-y-6">
      <Link to="/app" className="inline-flex items-center gap-1.5 text-[13px] text-fg-subtle transition hover:text-fg">
        <ArrowLeft className="size-3.5" /> Workspace
      </Link>

      {!ds ? (
        <Skeleton className="h-28 rounded-xl2" />
      ) : (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-4">
          <div className="relative shrink-0">
            <div className="absolute inset-0 -z-10 rounded-full blur-2xl" style={{ background: `${tone.hex}40` }} />
            <div className="sm:hidden">
              <QualityRing score={ds.quality_score} size={56} stroke={5} />
            </div>
            <div className="hidden sm:block">
              <QualityRing score={ds.quality_score} size={76} stroke={6} />
            </div>
          </div>
          <div className="min-w-0 flex-1 basis-[calc(100%-80px)] sm:basis-0">
            <h1 className="truncate text-2xl font-semibold tracking-[-0.025em] sm:text-3xl">{ds.name}</h1>
            <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[13px] text-fg-subtle">
              {ready && (
                <>
                  <Badge tone="brand">{ds.source_format.toUpperCase()}</Badge>
                  <span className="font-mono">{ds.row_count.toLocaleString()} rows × {ds.column_count} cols</span>
                  <span className="hidden sm:inline">·</span>
                  <span className="hidden sm:inline">{bytes(ds.size_bytes)} in → {bytes(ds.stored_bytes)} encrypted</span>
                  <span className="hidden sm:inline">·</span>
                  <span>analysed in {ms(ds.processing_ms)}</span>
                  <Badge tone="positive">
                    <Lock className="size-3" /> AES-256-GCM
                  </Badge>
                </>
              )}
              {ds.status === "failed" && <span className="text-sev-critical">{ds.error}</span>}
            </div>
          </div>
          {ready && <ActionsMenu ds={ds} />}
        </div>
      )}

      {ds && (ds.status === "queued" || ds.status === "processing") && <Processing ds={ds} />}
      {ds?.status === "failed" && (
        <Card>
          <Empty icon={<Lock className="size-5" />} title="This file could not be analysed" body={ds.error ?? undefined} action={<Link to="/app"><Button variant="primary">Upload another file</Button></Link>} />
        </Card>
      )}

      {ready && (
        <>
          <div className="sticky top-14 z-20 -mx-4 border-b border-white/[0.06] bg-ink-950/75 px-4 py-2 backdrop-blur-xl sm:-mx-6 sm:px-6 lg:top-0 lg:-mx-10 lg:px-10">
            <Tabs tabs={tabs} value={tab} onChange={setTab} layoutId="dataset-tab" />
          </div>
          {!r ? (
            <div className="grid gap-4 md:grid-cols-3">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-48 rounded-xl2" />
              ))}
            </div>
          ) : (
            <motion.div key={tab} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}>
              {tab === "overview" && <Overview ds={ds!} report={r} goTo={setTab} />}
              {tab === "insights" && <InsightsTab report={r} />}
              {tab === "columns" && <ColumnsTab report={r} />}
              {tab === "correlations" && <CorrelationsTab report={r} />}
              {tab === "trends" && <TrendsTab report={r} />}
              {tab === "privacy" && <PrivacyTab ds={ds!} report={r} />}
              {tab === "explore" && <ExploreTab ds={ds!} report={r} />}
              {tab === "data" && <DataTab ds={ds!} />}
            </motion.div>
          )}
        </>
      )}
    </div>
  );
}

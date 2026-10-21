import { useQueryClient } from "@tanstack/react-query";
import { Check, FileUp, FlaskConical, Loader2, UploadCloud, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { api, ApiError, streamProgress } from "../lib/api";
import { bytes } from "../lib/format";
import type { ProgressEvent } from "../lib/types";
import { Button, Card, cx } from "./ui";

export const PIPELINE = [
  { id: "validate", label: "Validate" },
  { id: "parse", label: "Parse" },
  { id: "clean", label: "Clean" },
  { id: "profile", label: "Profile" },
  { id: "privacy", label: "PII scan" },
  { id: "insights", label: "Insights" },
  { id: "secure", label: "Encrypt" },
];

interface Job {
  key: string;
  name: string;
  size: number;
  upload: number;
  id?: string;
  event?: ProgressEvent;
  error?: string;
}

function JobRow({ job, onDone, onDismiss }: { job: Job; onDone: (id: string, ok: boolean, message?: string | null) => void; onDismiss: () => void }) {
  const [event, setEvent] = useState<ProgressEvent | undefined>(job.event);
  const navigate = useNavigate();
  const finished = useRef(false);

  useEffect(() => {
    if (!job.id) return;
    const ctrl = new AbortController();
    streamProgress(
      job.id,
      (e) => {
        setEvent(e);
        if ((e.status === "ready" || e.status === "failed") && !finished.current) {
          finished.current = true;
          onDone(job.id!, e.status === "ready", e.message);
        }
      },
      ctrl.signal,
    ).catch(() => undefined);
    return () => ctrl.abort();
  }, [job.id, onDone]);

  const stageIdx = event ? PIPELINE.findIndex((s) => s.id === event.stage) : -1;
  const ready = event?.status === "ready";
  const failed = event?.status === "failed" || !!job.error;
  const uploading = !job.id && !job.error;

  return (
    <motion.div layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97 }} className="rounded-xl border border-white/[0.07] bg-ink-900/60 p-4">
      <div className="flex items-center gap-3">
        <div className={cx("grid size-9 shrink-0 place-items-center rounded-lg", ready ? "bg-mint/15 text-mint" : failed ? "bg-sev-critical/15 text-sev-critical" : "bg-brand-500/15 text-brand-300")}>
          {ready ? <Check className="size-4" /> : failed ? <X className="size-4" /> : <Loader2 className="size-4 animate-spin" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{job.name}</div>
          <div className="truncate text-[12px] text-fg-subtle">
            {bytes(job.size)} ·{" "}
            {uploading
              ? `Uploading ${Math.round(job.upload * 100)}%`
              : failed
                ? <span className="text-sev-critical">{job.error ?? event?.message}</span>
                : ready
                  ? <span className="text-mint">{event?.message ?? "Ready"}</span>
                  : event?.message ?? PIPELINE[Math.max(0, stageIdx)]?.label ?? "Queued"}
          </div>
        </div>
        {ready && job.id && (
          <Button size="sm" variant="primary" onClick={() => navigate(`/app/datasets/${job.id}`)}>
            Open
          </Button>
        )}
        {(ready || failed) && (
          <button onClick={onDismiss} aria-label="Dismiss" className="grid size-8 place-items-center rounded-lg text-fg-subtle hover:bg-white/[0.05] hover:text-fg">
            <X className="size-4" />
          </button>
        )}
      </div>
      <div className="mt-3.5 grid grid-cols-7 gap-1.5">
        {PIPELINE.map((s, i) => {
          const done = ready || i < stageIdx;
          const active = !ready && !failed && i === stageIdx;
          return (
            <div key={s.id} className="min-w-0">
              <div className="h-1 overflow-hidden rounded-full bg-white/[0.06]">
                <motion.div
                  className={cx("h-full rounded-full", failed && i >= stageIdx ? "bg-sev-critical/60" : "bg-brand-gradient")}
                  initial={false}
                  animate={{ width: done ? "100%" : active ? "60%" : uploading && i === 0 ? `${job.upload * 100}%` : "0%" }}
                  transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
                />
              </div>
              <div className={cx("mt-1.5 truncate text-[10.5px] font-medium", done ? "text-fg-muted" : active ? "text-brand-300" : "text-fg-subtle/70")}>{s.label}</div>
            </div>
          );
        })}
      </div>
    </motion.div>
  );
}

export function UploadPanel({ maxMb = 200 }: { maxMb?: number }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const navigate = useNavigate();

  const patch = (key: string, p: Partial<Job>) => setJobs((js) => js.map((j) => (j.key === key ? { ...j, ...p } : j)));

  const start = useCallback(
    async (file: File) => {
      const key = `${file.name}-${Date.now()}-${Math.random()}`;
      if (file.size > maxMb * 1024 * 1024) {
        toast.error(`${file.name} is larger than ${maxMb} MB`);
        return;
      }
      setJobs((js) => [{ key, name: file.name, size: file.size, upload: 0 }, ...js]);
      try {
        const ds = await api.upload(file, (f) => patch(key, { upload: f }));
        patch(key, { id: ds.id, upload: 1 });
        qc.invalidateQueries({ queryKey: ["datasets"] });
      } catch (e) {
        patch(key, { error: e instanceof ApiError ? e.message : "Upload failed" });
      }
    },
    [maxMb, qc],
  );

  const onDone = useCallback(
    (id: string, ok: boolean, message?: string | null) => {
      qc.invalidateQueries({ queryKey: ["datasets"] });
      qc.invalidateQueries({ queryKey: ["system"] });
      if (ok) toast.success("Analysis ready", { description: message ?? undefined, action: { label: "Open", onClick: () => navigate(`/app/datasets/${id}`) } });
      else toast.error("Processing failed", { description: message ?? undefined });
    },
    [qc, navigate],
  );

  const onFiles = (files: FileList | null) => {
    if (!files) return;
    Array.from(files).forEach((f) => void start(f));
  };

  const trySample = async () => {
    const res = await fetch("/samples/messy_sales.csv");
    const blob = await res.blob();
    void start(new File([blob], "messy_sales.csv", { type: "text/csv" }));
  };

  return (
    <Card className="overflow-hidden p-2">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          onFiles(e.dataTransfer.files);
        }}
        className={cx(
          "relative flex flex-col items-center justify-center overflow-hidden rounded-[14px] border-2 border-dashed px-6 py-10 text-center transition-all duration-300",
          drag ? "scale-[0.99] border-brand-400 bg-brand-500/10" : "border-white/10 hover:border-white/20",
        )}
      >
        <motion.div animate={drag ? { y: -6, scale: 1.08 } : { y: 0, scale: 1 }} className="relative">
          <div className="absolute inset-0 -z-10 scale-150 rounded-full bg-brand-500/25 blur-2xl" />
          <div className="grid size-14 place-items-center rounded-2xl bg-brand-gradient text-white shadow-xl shadow-brand-600/30">
            <UploadCloud className="size-7" />
          </div>
        </motion.div>
        <h3 className="mt-5 text-lg font-semibold tracking-tight">Drop a dataset to analyse</h3>
        <p className="mt-1 text-sm text-fg-muted">CSV · TSV · JSON · NDJSON · Excel · Parquet · .gz, up to {maxMb} MB</p>
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          <Button variant="primary" icon={<FileUp className="size-4" />} onClick={() => inputRef.current?.click()}>
            Choose files
          </Button>
          <Button variant="secondary" icon={<FlaskConical className="size-4" />} onClick={trySample}>
            Try messy sample
          </Button>
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          accept=".csv,.tsv,.txt,.json,.ndjson,.jsonl,.xlsx,.parquet,.gz"
          onChange={(e) => {
            onFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      <AnimatePresence initial={false}>
        {jobs.length > 0 && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="space-y-2 px-1 pb-1 pt-2">
            <AnimatePresence initial={false}>
              {jobs.map((j) => (
                <JobRow key={j.key} job={j} onDone={onDone} onDismiss={() => setJobs((js) => js.filter((x) => x.key !== j.key))} />
              ))}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}

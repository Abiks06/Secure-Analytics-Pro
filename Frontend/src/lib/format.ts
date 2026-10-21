import type { Severity } from "./types";

export function compact(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: digits }).format(v);
}

export function num(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const max = abs >= 1000 ? 0 : abs >= 10 ? 1 : digits;
  return new Intl.NumberFormat("en", { maximumFractionDigits: max }).format(v);
}

export function withUnit(v: number | null | undefined, unit: string | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const base = abs >= 10_000 ? compact(v) : num(v);
  if (unit?.startsWith("currency")) {
    const sym = unit.split(":")[1] ?? "";
    return sym.length === 1 ? `${v < 0 ? "-" : ""}${sym}${base.replace("-", "")}` : `${base} ${sym}`;
  }
  if (unit === "percent") return `${base}%`;
  return base;
}

export function pct(v: number | null | undefined, digits = 0): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(Math.abs(v) < 0.1 && v !== 0 ? Math.max(digits, 1) : digits)}%`;
}

export function bytes(n: number | null | undefined): string {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}`;
}

export function ms(v: number | null | undefined): string {
  if (v == null) return "—";
  return v < 1000 ? `${Math.round(v)} ms` : `${(v / 1000).toFixed(2)} s`;
}

export function ago(iso: string): string {
  const t = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`).getTime();
  const s = Math.round((Date.now() - t) / 1000);
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  if (s < 60) return rtf.format(-s, "second");
  if (s < 3600) return rtf.format(-Math.round(s / 60), "minute");
  if (s < 86400) return rtf.format(-Math.round(s / 3600), "hour");
  return rtf.format(-Math.round(s / 86400), "day");
}

export function dateLabel(iso: string, granularity?: string): string {
  const d = new Date(iso.length <= 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  if (granularity === "1y") return String(d.getFullYear());
  if (granularity === "1mo" || granularity === "1q")
    return d.toLocaleDateString("en", { month: "short", year: "2-digit" });
  if (granularity === "1h") return d.toLocaleString("en", { month: "short", day: "numeric", hour: "2-digit" });
  return d.toLocaleDateString("en", { month: "short", day: "numeric" });
}

export const severityStyle: Record<Severity, { label: string; text: string; bg: string; dot: string; hex: string }> = {
  critical: { label: "Critical", text: "text-sev-critical", bg: "bg-sev-critical/10", dot: "bg-sev-critical", hex: "#fb7185" },
  warning: { label: "Warning", text: "text-sev-warning", bg: "bg-sev-warning/10", dot: "bg-sev-warning", hex: "#fbbf24" },
  notable: { label: "Notable", text: "text-sev-notable", bg: "bg-sev-notable/10", dot: "bg-sev-notable", hex: "#a78bfa" },
  positive: { label: "Positive", text: "text-sev-positive", bg: "bg-sev-positive/10", dot: "bg-sev-positive", hex: "#34d399" },
  info: { label: "Info", text: "text-sev-info", bg: "bg-sev-info/10", dot: "bg-sev-info", hex: "#38bdf8" },
};

export function qualityTone(score: number | null | undefined): { label: string; hex: string } {
  if (score == null) return { label: "—", hex: "#6e7593" };
  if (score >= 90) return { label: "Excellent", hex: "#34d399" };
  if (score >= 75) return { label: "Good", hex: "#22d3ee" };
  if (score >= 60) return { label: "Fair", hex: "#fbbf24" };
  return { label: "Poor", hex: "#fb7185" };
}

/** "Datetime(time_unit='us', time_zone=None)" → "datetime", "Int64" → "int64". */
export function prettyType(t: string): string {
  return t.replace(/\(.*\)$/, "").toLowerCase();
}

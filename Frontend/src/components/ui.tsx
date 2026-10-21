import clsx from "clsx";
import { Loader2 } from "lucide-react";
import { motion } from "motion/react";
import { forwardRef, type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";
import { qualityTone, severityStyle } from "../lib/format";
import type { Severity } from "../lib/types";

export const cx = clsx;

type Variant = "primary" | "secondary" | "ghost" | "danger";
const variants: Record<Variant, string> = {
  primary:
    "bg-brand-gradient text-white shadow-[0_8px_30px_-8px_rgba(124,108,255,0.6)] hover:shadow-[0_10px_40px_-6px_rgba(124,108,255,0.75)] hover:brightness-110",
  secondary: "glass text-fg hover:bg-white/[0.07]",
  ghost: "text-fg-muted hover:text-fg hover:bg-white/[0.05]",
  danger: "bg-sev-critical/10 text-sev-critical border border-sev-critical/25 hover:bg-sev-critical/20",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cx(
        "inline-flex select-none items-center justify-center gap-2 rounded-xl font-medium transition-all duration-200 active:scale-[0.97] disabled:opacity-50 disabled:active:scale-100",
        size === "sm" && "h-8 px-3 text-[13px]",
        size === "md" && "h-10 px-4 text-sm",
        size === "lg" && "h-12 px-6 text-[15px]",
        variants[variant],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
});

export function Card({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("glass rounded-xl2", className)} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, icon, action }: { title: ReactNode; subtitle?: ReactNode; icon?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 px-5 pt-5">
      <div className="flex min-w-0 items-start gap-3">
        {icon && <div className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-white/[0.05] text-brand-300">{icon}</div>}
        <div className="min-w-0">
          <h3 className="truncate text-[15px] font-semibold tracking-tight text-fg">{title}</h3>
          {subtitle && <p className="mt-0.5 text-[13px] text-fg-subtle">{subtitle}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { icon?: ReactNode }>(function Input(
  { className, icon, ...rest },
  ref,
) {
  return (
    <div className="relative">
      {icon && <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle">{icon}</span>}
      <input
        ref={ref}
        className={cx(
          "h-11 w-full rounded-xl border border-white/10 bg-ink-900/70 px-3.5 text-[15px] text-fg placeholder:text-fg-subtle outline-none transition focus:border-brand-400/60 focus:bg-ink-900 focus:ring-4 focus:ring-brand-500/15",
          icon && "pl-10",
          className,
        )}
        {...rest}
      />
    </div>
  );
});

export function Badge({ children, className, tone = "neutral" }: { children: ReactNode; className?: string; tone?: Severity | "neutral" | "brand" }) {
  const toneClass =
    tone === "neutral"
      ? "bg-white/[0.06] text-fg-muted border-white/10"
      : tone === "brand"
        ? "bg-brand-500/12 text-brand-300 border-brand-400/25"
        : cx(severityStyle[tone].bg, severityStyle[tone].text, "border-current/20");
  return (
    <span className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium tracking-wide", toneClass, className)}>
      {children}
    </span>
  );
}

export function SeverityDot({ severity }: { severity: Severity }) {
  return (
    <span className="relative inline-flex size-2">
      {(severity === "critical" || severity === "warning") && (
        <span className={cx("absolute inline-flex size-full animate-ping rounded-full opacity-60", severityStyle[severity].dot)} />
      )}
      <span className={cx("relative inline-flex size-2 rounded-full", severityStyle[severity].dot)} />
    </span>
  );
}

export function QualityRing({ score, size = 64, stroke = 6, label = true }: { score: number | null; size?: number; stroke?: number; label?: boolean }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const value = Math.max(0, Math.min(100, score ?? 0));
  const tone = qualityTone(score);
  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth={stroke} />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={tone.hex}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          initial={{ strokeDashoffset: c }}
          animate={{ strokeDashoffset: c * (1 - value / 100) }}
          transition={{ duration: 1.2, ease: [0.22, 1, 0.36, 1] }}
          style={{ filter: `drop-shadow(0 0 6px ${tone.hex}66)` }}
        />
      </svg>
      {label && (
        <span className="absolute font-mono text-[13px] font-semibold tabular" style={{ fontSize: size * 0.24 }}>
          {score == null ? "—" : Math.round(score)}
        </span>
      )}
    </div>
  );
}

export function Meter({ value, color = "#8b7bff", className }: { value: number; color?: string; className?: string }) {
  return (
    <div className={cx("h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]", className)}>
      <motion.div
        className="h-full rounded-full"
        style={{ background: color }}
        initial={{ width: 0 }}
        animate={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
        transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
      />
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton rounded-lg", className)} />;
}

export function Empty({ icon, title, body, action }: { icon: ReactNode; title: string; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-4 grid size-12 place-items-center rounded-2xl bg-white/[0.05] text-brand-300 ring-1 ring-white/10">{icon}</div>
      <h3 className="text-base font-semibold">{title}</h3>
      {body && <p className="mt-1.5 max-w-sm text-sm text-fg-muted">{body}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  layoutId,
}: {
  tabs: { id: T; label: string; icon?: ReactNode; badge?: ReactNode }[];
  value: T;
  onChange: (v: T) => void;
  layoutId: string;
}) {
  return (
    <div className="no-scrollbar -mx-1 flex gap-1 overflow-x-auto px-1" role="tablist">
      {tabs.map((t) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.id)}
            className={cx(
              "relative flex h-9 shrink-0 items-center gap-2 rounded-lg px-3 text-[13px] font-medium transition-colors",
              active ? "text-fg" : "text-fg-subtle hover:text-fg-muted",
            )}
          >
            {active && (
              <motion.span
                layoutId={layoutId}
                className="absolute inset-0 rounded-lg bg-white/[0.07] ring-1 ring-white/10"
                transition={{ type: "spring", bounce: 0.18, duration: 0.45 }}
              />
            )}
            <span className="relative flex items-center gap-2">
              {t.icon}
              {t.label}
              {t.badge}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export function Stat({ label, value, hint, icon, accent }: { label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode; accent?: string }) {
  return (
    <Card className="relative overflow-hidden p-4">
      <div
        className="pointer-events-none absolute -right-8 -top-10 size-28 rounded-full opacity-25 blur-2xl"
        style={{ background: accent ?? "#8b7bff" }}
      />
      <div className="flex items-center gap-2 text-[12px] font-medium uppercase tracking-[0.08em] text-fg-subtle">
        {icon}
        {label}
      </div>
      <div className="mt-2 font-mono text-2xl font-semibold tracking-tight tabular">{value}</div>
      {hint && <div className="mt-1 text-[12.5px] text-fg-muted">{hint}</div>}
    </Card>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-white/15 bg-white/[0.06] px-1.5 py-0.5 font-mono text-[11px] text-fg-muted">{children}</kbd>;
}

export function Select<T extends string>({
  value,
  onChange,
  options,
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  className?: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as T)}
      className={cx(
        "h-9 rounded-lg border border-white/10 bg-ink-900 px-2.5 text-[13px] text-fg outline-none transition hover:border-white/20 focus:border-brand-400/60",
        className,
      )}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

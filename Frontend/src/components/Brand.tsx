import { useId } from "react";
import { Link } from "react-router";
import { cx } from "./ui";

export function LogoMark({ className }: { className?: string }) {
  // Unique per instance: a shared id breaks when the first copy sits in a display:none subtree.
  const id = `sap-g${useId().replace(/:/g, "")}`;
  return (
    <svg viewBox="0 0 64 64" className={cx("size-8", className)} aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#a78bfa" />
          <stop offset=".55" stopColor="#22d3ee" />
          <stop offset="1" stopColor="#34d399" />
        </linearGradient>
      </defs>
      <path d="M32 4 8 13v17c0 15 10.4 26.6 24 30 13.6-3.4 24-15 24-30V13L32 4Z" fill="#0a0c14" stroke={`url(#${id})`} strokeWidth="4" strokeLinejoin="round" />
      <path d="M20 40V31M28 40V24M36 40v-12M44 40V20" stroke={`url(#${id})`} strokeWidth="5" strokeLinecap="round" />
    </svg>
  );
}

export function Logo({ to = "/", compact = false }: { to?: string; compact?: boolean }) {
  return (
    <Link to={to} className="group flex items-center gap-2.5">
      <LogoMark className="transition-transform duration-500 group-hover:rotate-[8deg]" />
      {!compact && (
        <span className="text-[15px] font-semibold tracking-tight">
          Secure Analytics <span className="text-gradient">Pro</span>
        </span>
      )}
    </Link>
  );
}

/** Slow-moving aurora blobs + fading grid. Pure CSS transforms, GPU-composited. */
export function Aurora({ intensity = 1 }: { intensity?: number }) {
  return (
    <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden" aria-hidden>
      <div className="absolute inset-0 bg-ink-950" />
      <div
        className="absolute -left-[20%] -top-[30%] h-[70vh] w-[70vw] rounded-full blur-[120px] animate-aurora will-change-transform"
        style={{ background: "radial-gradient(closest-side, rgba(124,108,255,0.38), transparent)", opacity: intensity }}
      />
      <div
        className="absolute -right-[15%] top-[10%] h-[60vh] w-[55vw] rounded-full blur-[120px] animate-aurora will-change-transform [animation-delay:-6s]"
        style={{ background: "radial-gradient(closest-side, rgba(34,211,238,0.22), transparent)", opacity: intensity }}
      />
      <div
        className="absolute bottom-[-30%] left-[25%] h-[60vh] w-[50vw] rounded-full blur-[120px] animate-aurora will-change-transform [animation-delay:-12s]"
        style={{ background: "radial-gradient(closest-side, rgba(52,211,153,0.16), transparent)", opacity: intensity }}
      />
      <div className="grid-bg absolute inset-0" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,transparent_0%,rgba(5,6,10,0.6)_70%)]" />
    </div>
  );
}

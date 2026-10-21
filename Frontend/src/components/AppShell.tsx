import { useQuery } from "@tanstack/react-query";
import { Database, LayoutGrid, LogOut, Menu, ShieldCheck, Sparkles, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { api, useAuth } from "../lib/api";
import { Aurora, Logo } from "./Brand";
import { cx, QualityRing } from "./ui";

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const user = useAuth((s) => s.user);
  const navigate = useNavigate();
  const { data: datasets } = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const { data: system } = useQuery({ queryKey: ["system"], queryFn: api.system, staleTime: 60_000 });
  const recent = (datasets ?? []).filter((d) => d.status === "ready").slice(0, 6);

  const link = ({ isActive }: { isActive: boolean }) =>
    cx(
      "group flex h-10 items-center gap-3 rounded-xl px-3 text-sm font-medium transition-all",
      isActive ? "bg-white/[0.07] text-fg ring-1 ring-white/10" : "text-fg-muted hover:bg-white/[0.04] hover:text-fg",
    );

  return (
    <div className="flex h-full flex-col gap-6 p-4">
      <div className="px-2 pt-1">
        <Logo to="/app" />
      </div>
      <nav className="flex flex-col gap-1">
        <NavLink to="/app" end className={link} onClick={onNavigate}>
          <LayoutGrid className="size-[18px]" /> Workspace
        </NavLink>
        <NavLink to="/app/security" className={link} onClick={onNavigate}>
          <ShieldCheck className="size-[18px]" /> Security Center
        </NavLink>
      </nav>

      <div className="min-h-0 flex-1">
        <div className="mb-2 flex items-center justify-between px-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-fg-subtle">
          <span>Recent datasets</span>
          <span className="font-mono">{datasets?.length ?? 0}</span>
        </div>
        <div className="flex flex-col gap-0.5">
          {recent.length === 0 && <p className="px-3 text-[13px] text-fg-subtle">Nothing analysed yet.</p>}
          {recent.map((d) => (
            <NavLink key={d.id} to={`/app/datasets/${d.id}`} onClick={onNavigate} className={link}>
              <QualityRing score={d.quality_score} size={22} stroke={3} label={false} />
              <span className="truncate">{d.name}</span>
            </NavLink>
          ))}
        </div>
      </div>

      <div className="glass rounded-xl p-3">
        <div className="flex items-center gap-2 text-[12px] text-fg-muted">
          <Sparkles className={cx("size-3.5", system?.ai_enabled ? "text-mint" : "text-fg-subtle")} />
          AI analyst {system?.ai_enabled ? <span className="text-mint">online</span> : <span>offline</span>}
        </div>
        <div className="mt-1.5 flex items-center gap-2 text-[12px] text-fg-muted">
          <Database className="size-3.5 text-cyan-glow" />
          {system?.database === "postgresql+rls" ? "Postgres · Row Level Security" : "SQLite · tenant-filtered"}
        </div>
      </div>

      <div className="flex items-center gap-3 rounded-xl px-2">
        <div className="grid size-9 shrink-0 place-items-center rounded-full bg-brand-gradient text-sm font-semibold text-white">
          {user?.name?.[0]?.toUpperCase() ?? "?"}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{user?.name}</div>
          <div className="truncate text-[12px] text-fg-subtle">{user?.email}</div>
        </div>
        <button
          aria-label="Sign out"
          title="Sign out"
          onClick={async () => {
            await api.logout();
            navigate("/login");
          }}
          className="grid size-8 place-items-center rounded-lg text-fg-subtle transition hover:bg-white/[0.06] hover:text-fg"
        >
          <LogOut className="size-4" />
        </button>
      </div>
    </div>
  );
}

export default function AppShell() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  return (
    <div className="min-h-dvh">
      <Aurora intensity={0.55} />
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[264px] border-r border-white/[0.06] bg-ink-950/60 backdrop-blur-xl lg:block">
        <Sidebar />
      </aside>

      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-white/[0.06] bg-ink-950/70 px-4 backdrop-blur-xl lg:hidden">
        <Logo to="/app" />
        <button aria-label="Open menu" onClick={() => setOpen(true)} className="grid size-9 place-items-center rounded-lg hover:bg-white/[0.06]">
          <Menu className="size-5" />
        </button>
      </header>
      <AnimatePresence>
        {open && (
          <>
            <motion.div className="fixed inset-0 z-40 bg-black/60 lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(false)} />
            <motion.aside
              className="glass-strong fixed inset-y-0 left-0 z-50 w-[284px] lg:hidden"
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ type: "spring", bounce: 0, duration: 0.35 }}
            >
              <button aria-label="Close menu" onClick={() => setOpen(false)} className="absolute right-3 top-4 grid size-8 place-items-center rounded-lg hover:bg-white/[0.06]">
                <X className="size-4" />
              </button>
              <Sidebar onNavigate={() => setOpen(false)} />
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      <main className="lg:pl-[264px]">
        <motion.div
          key={location.pathname}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:px-10 lg:py-9"
        >
          <Outlet />
        </motion.div>
      </main>
    </div>
  );
}

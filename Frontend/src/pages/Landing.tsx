import {
  ArrowRight,
  Binary,
  Bot,
  Check,
  FileWarning,
  Fingerprint,
  KeyRound,
  Link2,
  Lock,
  ScanSearch,
  Shield,
  Sparkles,
  Terminal,
  TrendingUp,
  Wand2,
} from "lucide-react";
import { AnimatePresence, motion, useInView } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { Aurora, Logo } from "../components/Brand";
import { Button, cx } from "../components/ui";
import { useAuth } from "../lib/api";

const ease = [0.22, 1, 0.36, 1] as const;

function Reveal({ children, delay = 0, className }: { children: ReactNode; delay?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });
  return (
    <motion.div
      ref={ref}
      className={className}
      initial={{ opacity: 0, y: 24 }}
      animate={inView ? { opacity: 1, y: 0 } : {}}
      transition={{ duration: 0.7, delay, ease }}
    >
      {children}
    </motion.div>
  );
}

const STAGES = ["Validating signature", "Decoding cp1252 → UTF-8", "Parsing 4 date formats", "Unifying 384 category variants", "Scanning for PII", "Discovering insights", "Encrypting AES-256-GCM"];

const DEMO_INSIGHTS = [
  { tone: "#fb7185", tag: "Privacy", title: "Card numbers detected — redacted by default" },
  { tone: "#34d399", tag: "Trend", title: "Revenue trending up 48% (p < 0.001)" },
  { tone: "#a78bfa", tag: "Driver", title: "Region explains 34% of order value" },
  { tone: "#fbbf24", tag: "Outlier", title: "12 orders are 40× the median — entry errors?" },
];

function ProductPreview() {
  const [step, setStep] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setStep((s) => (s + 1) % (STAGES.length + 5)), 900);
    return () => clearInterval(id);
  }, []);
  const done = step >= STAGES.length;
  const shown = Math.max(0, step - STAGES.length + 1);
  const path = "M0,80 C30,78 50,70 80,66 C110,62 130,70 160,52 C190,36 210,44 240,30 C270,18 300,22 330,10";
  return (
    <div className="ring-gradient glass-strong relative overflow-hidden rounded-[22px] shadow-[0_40px_120px_-30px_rgba(124,108,255,0.45)]">
      <div className="flex items-center gap-2 border-b border-white/[0.06] px-4 py-3">
        <span className="size-2.5 rounded-full bg-[#fb7185]/80" />
        <span className="size-2.5 rounded-full bg-[#fbbf24]/80" />
        <span className="size-2.5 rounded-full bg-[#34d399]/80" />
        <span className="ml-3 min-w-0 truncate font-mono text-[11px] text-fg-subtle">messy_sales_export (3).csv · 5,050 rows</span>
        <span className="ml-auto flex items-center gap-1.5 rounded-full bg-mint/10 px-2 py-0.5 text-[10.5px] font-medium text-mint">
          <Lock className="size-3" /> encrypted
        </span>
      </div>
      <div className="grid gap-4 p-4 sm:grid-cols-[1fr_1.25fr]">
        <div className="space-y-1.5">
          {STAGES.map((s, i) => {
            const state = i < step ? "done" : i === step ? "active" : "todo";
            return (
              <div key={s} className={cx("flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[12.5px] transition-colors", state === "active" && "bg-white/[0.05]")}>
                <span
                  className={cx(
                    "grid size-4 shrink-0 place-items-center rounded-full border text-[9px]",
                    state === "done" && "border-mint/50 bg-mint/15 text-mint",
                    state === "active" && "border-brand-400 text-brand-300",
                    state === "todo" && "border-white/15 text-transparent",
                  )}
                >
                  {state === "done" ? <Check className="size-2.5" /> : state === "active" ? <span className="size-1.5 animate-ping rounded-full bg-brand-400" /> : null}
                </span>
                <span className={state === "todo" ? "text-fg-subtle" : "text-fg-muted"}>{s}</span>
              </div>
            );
          })}
        </div>
        <div className="flex flex-col gap-3">
          <div className="rounded-xl border border-white/[0.06] bg-ink-900/70 p-3">
            <div className="flex items-baseline justify-between">
              <span className="text-[11px] uppercase tracking-wider text-fg-subtle">Revenue / month</span>
              <span className="font-mono text-[12px] text-mint">+48.2%</span>
            </div>
            <svg viewBox="0 0 330 90" className="mt-2 h-24 w-full overflow-visible">
              <defs>
                <linearGradient id="lp-area" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor="#8b7bff" stopOpacity=".45" />
                  <stop offset="1" stopColor="#8b7bff" stopOpacity="0" />
                </linearGradient>
              </defs>
              <motion.path d={`${path} L330,90 L0,90 Z`} fill="url(#lp-area)" initial={{ opacity: 0 }} animate={{ opacity: done ? 1 : 0.15 }} transition={{ duration: 0.8 }} />
              <motion.path d={path} fill="none" stroke="#8b7bff" strokeWidth="2.5" strokeLinecap="round" initial={{ pathLength: 0 }} animate={{ pathLength: done ? 1 : 0.25 }} transition={{ duration: 1.2, ease }} />
              <motion.path d="M330,10 L360,4 L390,-4" fill="none" stroke="#22d3ee" strokeWidth="2" strokeDasharray="4 4" initial={{ opacity: 0 }} animate={{ opacity: done ? 1 : 0 }} />
              <motion.circle cx="240" cy="30" r="5" fill="#fb7185" stroke="#090b12" strokeWidth="2" initial={{ scale: 0 }} animate={{ scale: done ? 1 : 0 }} transition={{ delay: 0.6, type: "spring" }} />
            </svg>
          </div>
          <div className="space-y-2">
            <AnimatePresence initial={false}>
              {DEMO_INSIGHTS.slice(0, shown).map((ins) => (
                <motion.div
                  key={ins.title}
                  initial={{ opacity: 0, y: 10, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.4, ease }}
                  className="flex items-center gap-2.5 rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-2"
                >
                  <span className="size-1.5 shrink-0 rounded-full" style={{ background: ins.tone, boxShadow: `0 0 10px ${ins.tone}` }} />
                  <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: ins.tone }}>
                    {ins.tag}
                  </span>
                  <span className="truncate text-[12.5px] text-fg-muted">{ins.title}</span>
                </motion.div>
              ))}
            </AnimatePresence>
            {shown === 0 && (
              <div className="space-y-2">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="skeleton h-9 rounded-lg" />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="pointer-events-none absolute inset-x-0 top-0 h-24 animate-scan bg-gradient-to-b from-transparent via-cyan-glow/[0.06] to-transparent" />
    </div>
  );
}

const FEATURES = [
  {
    icon: <Wand2 className="size-5" />,
    title: "Self-cleaning ingestion",
    body: "CSV, TSV, JSON, NDJSON, Excel, Parquet, even gzipped. Currency, European decimals, accounting negatives, mixed date formats and typo'd categories are fixed, and every fix is logged.",
    span: "lg:col-span-2",
    visual: (
      <div className="mt-5 grid grid-cols-2 gap-2 font-mono text-[11.5px]">
        {[
          ["\"$1,200.50\"", "1200.50"],
          ["(300)", "-300.00"],
          ["Mar 05, 2024", "2024-03-05"],
          [" west ", "West"],
          ["N/A", "∅"],
          ["1.234,50", "1234.50"],
        ].map(([a, b]) => (
          <div key={a} className="flex items-center gap-2 rounded-lg bg-white/[0.03] px-2.5 py-1.5">
            <span className="truncate text-sev-critical/80 line-through decoration-sev-critical/40">{a}</span>
            <ArrowRight className="size-3 shrink-0 text-fg-subtle" />
            <span className="truncate text-mint">{b}</span>
          </div>
        ))}
      </div>
    ),
  },
  {
    icon: <Fingerprint className="size-5" />,
    title: "PII shield",
    body: "13 personal-data types detected with checksum validation (Luhn, IBAN mod-97). Masked, pseudonymised or redacted before anyone sees them.",
    visual: (
      <div className="mt-5 space-y-1.5 font-mono text-[12px]">
        <div className="rounded-lg bg-white/[0.03] px-2.5 py-1.5 text-fg-muted">a•••@e•••.com</div>
        <div className="rounded-lg bg-white/[0.03] px-2.5 py-1.5 text-fg-muted">•••• 4242</div>
        <div className="rounded-lg bg-white/[0.03] px-2.5 py-1.5 text-sev-critical/80">[REDACTED]</div>
      </div>
    ),
  },
  {
    icon: <ScanSearch className="size-5" />,
    title: "Insight engine",
    body: "Correlations, segment drivers (η²), Pareto concentration, robust outliers, multivariate anomalies, Mann-Kendall trends and Holt forecasts, ranked by effect size.",
  },
  {
    icon: <Terminal className="size-5" />,
    title: "Sandboxed SQL",
    body: "DuckDB over a zero-copy Arrow view, with no file or network access, a single SELECT only, plus row, memory and time limits.",
  },
  {
    icon: <Bot className="size-5" />,
    title: "AI analyst",
    body: "Ask in plain English. Claude writes the SQL, the sandbox runs it, and you get the answer with a chart. Claude only ever sees schema, statistics and masked results.",
  },
];

const SECURITY = [
  { icon: <KeyRound className="size-4" />, title: "Envelope encryption", body: "A unique AES-256-GCM key per dataset, wrapped by a master key. Deleting the key crypto-shreds the data." },
  { icon: <Shield className="size-4" />, title: "Supabase Auth", body: "Email-verified accounts. Short-lived ES256 access tokens, checked against public keys and live session state on every request." },
  { icon: <Link2 className="size-4" />, title: "Tamper-evident audit", body: "Every action is hash-chained. Edit one log row and verification pinpoints where the chain broke." },
  { icon: <Binary className="size-4" />, title: "Row Level Security", body: "Forced RLS on every table, enforced on a least-privilege engine role. Even a query bug cannot read another user's rows." },
  { icon: <FileWarning className="size-4" />, title: "Hostile-file hardened", body: "Magic-byte sniffing, decompression-bomb limits, and CSV formula-injection neutralised on export." },
  { icon: <Lock className="size-4" />, title: "Instant session revocation", body: "Refresh tokens rotate on every use and replays are rejected. Revoke any device and its access stops on the next request." },
];

function ChainVisual() {
  const blocks = [
    { seq: 41, action: "dataset.upload", hash: "9f2c…a71e" },
    { seq: 42, action: "privacy.update", hash: "1b8d…44c0" },
    { seq: 43, action: "dataset.query", hash: "e05a…9d12" },
  ];
  return (
    <div className="space-y-3">
      {blocks.map((b, i) => (
        <Reveal key={b.seq} delay={i * 0.12}>
          <div className="glass relative rounded-xl p-4 font-mono text-[12px]">
            <div className="flex items-center justify-between">
              <span className="text-brand-300">#{b.seq}</span>
              <span className="text-fg-muted">{b.action}</span>
              <span className="flex items-center gap-1 text-mint">
                <Check className="size-3" /> verified
              </span>
            </div>
            <div className="mt-2 truncate text-fg-subtle">
              sha256(prev ‖ event) = <span className="text-cyan-glow">{b.hash}</span>
            </div>
            {i < blocks.length - 1 && <div className="absolute -bottom-3 left-8 h-3 w-px bg-gradient-to-b from-brand-400 to-cyan-glow" />}
          </div>
        </Reveal>
      ))}
    </div>
  );
}

export default function Landing() {
  const authed = useAuth((s) => s.status === "authed");
  const cta = authed ? "/app" : "/register";
  return (
    <div className="relative min-h-dvh overflow-x-clip">
      <Aurora />
      <header className="sticky top-0 z-40 border-b border-white/[0.04] bg-ink-950/50 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6">
          <Logo />
          <nav className="hidden items-center gap-8 text-sm text-fg-muted md:flex">
            <a href="#features" className="transition hover:text-fg">Features</a>
            <a href="#how" className="transition hover:text-fg">How it works</a>
            <a href="#security" className="transition hover:text-fg">Security</a>
          </nav>
          <div className="flex items-center gap-2">
            {!authed && (
              <Link to="/login" className="hidden h-9 items-center rounded-lg px-3 text-sm text-fg-muted transition hover:text-fg sm:flex">
                Sign in
              </Link>
            )}
            <Link to={cta}>
              <Button variant="primary" size="sm">
                {authed ? "Open workspace" : "Get started"} <ArrowRight className="size-3.5" />
              </Button>
            </Link>
          </div>
        </div>
      </header>

      <section className="mx-auto grid max-w-7xl grid-cols-1 items-center gap-14 px-4 pb-20 pt-16 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:pt-24">
        <div>
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease }}>
            <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[12px] text-fg-muted">
              <Sparkles className="size-3.5 text-brand-300" />
              v2: encrypted analytics engine with an AI analyst
            </span>
          </motion.div>
          <motion.h1
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.08, ease }}
            className="mt-6 text-[clamp(2.6rem,6vw,4.6rem)] font-semibold leading-[1.02] tracking-[-0.035em]"
          >
            Messy data in.
            <br />
            <span className="text-gradient">Trusted insight</span> out.
          </motion.h1>
          <motion.p
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.16, ease }}
            className="mt-6 max-w-xl text-lg leading-relaxed text-fg-muted"
          >
            Drop in any spreadsheet export or API dump. Secure Analytics Pro cleans it, profiles it, finds what matters and
            explains why, while keeping personal data masked and everything encrypted at rest.
          </motion.p>
          <motion.div initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.24, ease }} className="mt-9 flex flex-wrap gap-3">
            <Link to={cta}>
              <Button variant="primary" size="lg">
                Analyse a dataset free <ArrowRight className="size-4" />
              </Button>
            </Link>
            <a href="#security">
              <Button variant="secondary" size="lg" icon={<Shield className="size-4" />}>
                Security model
              </Button>
            </a>
          </motion.div>
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.5, duration: 1 }} className="mt-10 flex flex-wrap gap-x-6 gap-y-2 font-mono text-[12px] text-fg-subtle">
            {["AES-256-GCM", "Supabase Auth", "ES256 JWT", "Postgres RLS", "SHA-256 audit chain"].map((t) => (
              <span key={t} className="flex items-center gap-1.5">
                <Check className="size-3 text-mint" /> {t}
              </span>
            ))}
          </motion.div>
        </div>
        <motion.div initial={{ opacity: 0, y: 30, rotateX: 8 }} animate={{ opacity: 1, y: 0, rotateX: 0 }} transition={{ duration: 1, delay: 0.2, ease }} style={{ perspective: 1200 }} className="min-w-0">
          <ProductPreview />
        </motion.div>
      </section>

      <section className="mx-auto max-w-7xl px-4 sm:px-6">
        <Reveal>
          <div className="glass grid grid-cols-2 divide-white/[0.06] rounded-2xl md:grid-cols-4 md:divide-x">
            {[
              ["< 1 s", "to clean & profile 5k messy rows"],
              ["9", "insight detectors, ranked by effect"],
              ["0 bytes", "of plaintext data written to disk"],
              ["13", "PII types with checksum validation"],
            ].map(([k, v]) => (
              <div key={k} className="p-6">
                <div className="text-gradient font-mono text-3xl font-semibold tracking-tight">{k}</div>
                <div className="mt-1 text-[13px] text-fg-muted">{v}</div>
              </div>
            ))}
          </div>
        </Reveal>
      </section>

      <section id="features" className="mx-auto max-w-7xl scroll-mt-20 px-4 py-28 sm:px-6">
        <Reveal className="max-w-2xl">
          <p className="text-sm font-medium text-brand-300">Everything between the upload and the answer</p>
          <h2 className="mt-3 text-4xl font-semibold tracking-[-0.03em] sm:text-5xl">An analyst, a data engineer and a security team in one pipeline.</h2>
        </Reveal>
        <div className="mt-14 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f, i) => (
            <Reveal key={f.title} delay={i * 0.06} className={f.span}>
              <div className="group glass relative h-full overflow-hidden rounded-2xl p-6 transition duration-500 hover:-translate-y-1 hover:border-white/15">
                <div className="pointer-events-none absolute -right-20 -top-20 size-56 rounded-full bg-brand-500/10 opacity-0 blur-3xl transition duration-700 group-hover:opacity-100" />
                <div className="grid size-10 place-items-center rounded-xl bg-brand-gradient text-white shadow-lg shadow-brand-600/30">{f.icon}</div>
                <h3 className="mt-5 text-lg font-semibold tracking-tight">{f.title}</h3>
                <p className="mt-2 text-[14.5px] leading-relaxed text-fg-muted">{f.body}</p>
                {f.visual}
              </div>
            </Reveal>
          ))}
          <Reveal delay={0.3}>
            <div className="glass relative h-full overflow-hidden rounded-2xl p-6">
              <div className="grid size-10 place-items-center rounded-xl bg-brand-gradient text-white">
                <TrendingUp className="size-5" />
              </div>
              <h3 className="mt-5 text-lg font-semibold tracking-tight">Forecasts with honest error bars</h3>
              <p className="mt-2 text-[14.5px] leading-relaxed text-fg-muted">Holt smoothing, fitted by grid search, with prediction intervals that widen with the horizon. Partial periods are detected so they can't fake a drop.</p>
            </div>
          </Reveal>
        </div>
      </section>

      <section id="how" className="mx-auto max-w-7xl scroll-mt-20 px-4 pb-28 sm:px-6">
        <Reveal className="max-w-2xl">
          <p className="text-sm font-medium text-brand-300">How it works</p>
          <h2 className="mt-3 text-4xl font-semibold tracking-[-0.03em]">Three steps. Seconds, not sprints.</h2>
        </Reveal>
        <div className="relative mt-14 grid gap-6 md:grid-cols-3">
          <div className="absolute left-0 right-0 top-7 hidden h-px bg-gradient-to-r from-transparent via-brand-400/40 to-transparent md:block" />
          {[
            ["01", "Upload anything", "Drag in a file up to 200 MB. It's validated by its bytes, not its name, and streamed straight into memory."],
            ["02", "Watch it analyse", "Live progress streams every stage: decode, clean, profile, PII scan, insight discovery, encryption."],
            ["03", "Explore & share safely", "Interactive insights, SQL, an AI analyst and privacy-safe exports. Every action lands in your audit trail."],
          ].map(([n, t, b], i) => (
            <Reveal key={n} delay={i * 0.1}>
              <div className="relative">
                <div className="glass relative z-10 grid size-14 place-items-center rounded-2xl font-mono text-lg font-semibold text-gradient">{n}</div>
                <h3 className="mt-5 text-lg font-semibold">{t}</h3>
                <p className="mt-2 text-[14.5px] leading-relaxed text-fg-muted">{b}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      <section id="security" className="mx-auto max-w-7xl scroll-mt-20 px-4 pb-28 sm:px-6">
        <div className="grid items-start gap-12 lg:grid-cols-[1.2fr_1fr]">
          <div>
            <Reveal>
              <p className="text-sm font-medium text-brand-300">Security by construction</p>
              <h2 className="mt-3 text-4xl font-semibold tracking-[-0.03em]">The word “Secure” is in the name. We took it literally.</h2>
            </Reveal>
            <div className="mt-10 grid gap-x-8 gap-y-7 sm:grid-cols-2">
              {SECURITY.map((s, i) => (
                <Reveal key={s.title} delay={i * 0.05}>
                  <div className="flex gap-3">
                    <div className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-white/[0.05] text-cyan-glow ring-1 ring-white/10">{s.icon}</div>
                    <div>
                      <h3 className="font-semibold">{s.title}</h3>
                      <p className="mt-1 text-[14px] leading-relaxed text-fg-muted">{s.body}</p>
                    </div>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
          <ChainVisual />
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 pb-24 sm:px-6">
        <Reveal>
          <div className="ring-gradient relative overflow-hidden rounded-3xl bg-gradient-to-br from-brand-600/25 via-ink-900 to-cyan-glow/10 px-6 py-16 text-center sm:px-16">
            <div className="grid-bg absolute inset-0 opacity-60" />
            <h2 className="relative text-4xl font-semibold tracking-[-0.03em] sm:text-5xl">Your messiest file is the best demo.</h2>
            <p className="relative mx-auto mt-4 max-w-xl text-fg-muted">Create an account, drop it in, and see what it's been hiding.</p>
            <Link to={cta} className="relative mt-8 inline-block">
              <Button variant="primary" size="lg">
                Start analysing <ArrowRight className="size-4" />
              </Button>
            </Link>
          </div>
        </Reveal>
      </section>

      <footer className="border-t border-white/[0.06]">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-4 py-8 text-[13px] text-fg-subtle sm:flex-row sm:px-6">
          <Logo />
          <span>FastAPI · Polars · DuckDB · React. Built for data you can't afford to leak.</span>
        </div>
      </footer>
    </div>
  );
}

import { ArrowRight, Eye, EyeOff, Lock, Mail, ShieldCheck, User as UserIcon } from "lucide-react";
import { motion } from "motion/react";
import { useMemo, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { Aurora, Logo, LogoMark } from "../components/Brand";
import { Button, cx, Input } from "../components/ui";
import { api, ApiError } from "../lib/api";

function strength(pw: string, email: string) {
  const checks = [
    { ok: pw.length >= 10, label: "10+ characters" },
    { ok: /[a-z]/.test(pw) && /[A-Z]/.test(pw), label: "Upper & lower case" },
    { ok: /\d/.test(pw), label: "A number" },
    { ok: /[^A-Za-z0-9]/.test(pw), label: "A symbol" },
  ];
  const local = email.split("@")[0]?.toLowerCase() ?? "";
  const containsEmail = local.length >= 4 && pw.toLowerCase().includes(local);
  const score = checks.filter((c) => c.ok).length - (containsEmail ? 2 : 0) + (pw.length >= 16 ? 1 : 0);
  return { checks, score: Math.max(0, Math.min(5, score)), containsEmail };
}

const STRENGTH = ["#fb7185", "#fb7185", "#fbbf24", "#fbbf24", "#22d3ee", "#34d399"];

export default function AuthPage({ mode }: { mode: "login" | "register" }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isRegister = mode === "register";
  const s = useMemo(() => strength(password, email), [password, email]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (isRegister) await api.register(name, email, password);
      else await api.login(email, password);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from.startsWith("/app") ? from : "/app", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-dvh lg:grid-cols-[1fr_1.05fr]">
      <Aurora intensity={0.7} />
      <div className="flex flex-col px-6 py-8 sm:px-12">
        <Logo />
        <div className="flex flex-1 items-center justify-center py-12">
          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }} className="w-full max-w-sm">
            <h1 className="text-3xl font-semibold tracking-[-0.03em]">{isRegister ? "Create your workspace" : "Welcome back"}</h1>
            <p className="mt-2 text-fg-muted">
              {isRegister ? "Encrypted, private by default, ready in seconds." : "Sign in to your secure analytics workspace."}
            </p>

            <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
              {isRegister && (
                <label className="block">
                  <span className="mb-1.5 block text-[13px] font-medium text-fg-muted">Name</span>
                  <Input icon={<UserIcon className="size-4" />} value={name} onChange={(e) => setName(e.target.value)} placeholder="Ada Lovelace" autoComplete="name" required />
                </label>
              )}
              <label className="block">
                <span className="mb-1.5 block text-[13px] font-medium text-fg-muted">Email</span>
                <Input icon={<Mail className="size-4" />} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" autoComplete="email" required />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-[13px] font-medium text-fg-muted">Password</span>
                <div className="relative">
                  <Input
                    icon={<Lock className="size-4" />}
                    type={show ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder={isRegister ? "At least 10 characters" : "••••••••••"}
                    autoComplete={isRegister ? "new-password" : "current-password"}
                    className="pr-11"
                    required
                  />
                  <button type="button" onClick={() => setShow((v) => !v)} aria-label={show ? "Hide password" : "Show password"} className="absolute right-2 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-lg text-fg-subtle hover:text-fg">
                    {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                  </button>
                </div>
              </label>

              {isRegister && password && (
                <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} className="space-y-2">
                  <div className="flex gap-1">
                    {[0, 1, 2, 3, 4].map((i) => (
                      <div key={i} className="h-1 flex-1 rounded-full transition-colors duration-300" style={{ background: i < s.score ? STRENGTH[s.score] : "rgba(255,255,255,0.08)" }} />
                    ))}
                  </div>
                  <div className="grid grid-cols-2 gap-1 text-[12px]">
                    {s.checks.map((c) => (
                      <span key={c.label} className={c.ok ? "text-mint" : "text-fg-subtle"}>
                        {c.ok ? "✓" : "○"} {c.label}
                      </span>
                    ))}
                  </div>
                  {s.containsEmail && <p className="text-[12px] text-sev-warning">Don't reuse your email name in the password.</p>}
                </motion.div>
              )}

              {error && (
                <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} role="alert" className="rounded-xl border border-sev-critical/25 bg-sev-critical/10 px-3.5 py-2.5 text-[13.5px] text-sev-critical">
                  {error}
                </motion.div>
              )}

              <Button type="submit" variant="primary" size="lg" className="w-full" loading={busy}>
                {isRegister ? "Create account" : "Sign in"} {!busy && <ArrowRight className="size-4" />}
              </Button>
            </form>

            <p className="mt-6 text-center text-sm text-fg-muted">
              {isRegister ? "Already have an account? " : "New here? "}
              <Link to={isRegister ? "/login" : "/register"} className="font-medium text-brand-300 hover:text-brand-400">
                {isRegister ? "Sign in" : "Create an account"}
              </Link>
            </p>
          </motion.div>
        </div>
        <p className="flex items-center gap-2 text-[12px] text-fg-subtle">
          <ShieldCheck className="size-3.5 text-mint" /> Passwords are hashed with Argon2id. Sessions use rotating httpOnly tokens.
        </p>
      </div>

      <div className="relative hidden overflow-hidden border-l border-white/[0.06] lg:block">
        <div className="absolute inset-0 bg-gradient-to-br from-brand-600/20 via-ink-900/40 to-cyan-glow/10" />
        <div className="grid-bg absolute inset-0" />
        <div className="relative flex h-full flex-col items-center justify-center p-12">
          <motion.div animate={{ y: [0, -12, 0] }} transition={{ duration: 7, repeat: Infinity, ease: "easeInOut" }} className="relative">
            <div className="absolute inset-0 -z-10 scale-150 rounded-full bg-brand-500/30 blur-3xl" />
            <LogoMark className="size-28 drop-shadow-[0_0_40px_rgba(139,123,255,0.5)]" />
          </motion.div>
          <div className="mt-12 w-full max-w-md space-y-3">
            {[
              ["Encrypted at rest", "AES-256-GCM · per-dataset keys"],
              ["Private by default", "PII masked before anyone sees it"],
              ["Provable history", "SHA-256 hash-chained audit log"],
            ].map(([t, d], i) => (
              <motion.div
                key={t}
                initial={{ opacity: 0, x: 24 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.3 + i * 0.12, duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
                className={cx("glass flex items-center justify-between rounded-xl px-4 py-3")}
              >
                <span className="font-medium">{t}</span>
                <span className="font-mono text-[12px] text-fg-subtle">{d}</span>
              </motion.div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Button, cx, ErrorBox, Icon } from "../components/ui";
import { DEMO_ACCOUNTS, HOME, startSession, useAuth } from "../lib/auth";

export default function LoginPage() {
  const { user } = useAuth();
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () => api.login(username.trim(), password),
    onSuccess: (r) => { startSession(r); nav(HOME[r.user.role], { replace: true }); },
  });
  if (user) return <Navigate to={HOME[user.role]} replace />;

  return (
    <div className="flex min-h-full flex-col bg-white lg:flex-row">
      {/* brand panel */}
      <div className="relative flex flex-col justify-between overflow-hidden bg-brand-700 px-8 py-10 text-white lg:w-[44%] lg:px-14 lg:py-14">
        <div className="pointer-events-none absolute -right-24 -top-24 h-80 w-80 rounded-full bg-white/10" />
        <div className="pointer-events-none absolute -bottom-32 -left-16 h-96 w-96 rounded-full bg-white/5" />
        <div className="relative flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-white/15 ring-1 ring-white/25">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
              <circle cx="10.5" cy="10.5" r="5.5" /><path d="m15 15 5 5" />
            </svg>
          </div>
          <div>
            <div className="text-lg font-semibold tracking-tight">CaseLens</div>
            <div className="text-xs text-white/70">Fan-pattern review</div>
          </div>
        </div>
        <div className="relative my-10 max-w-md lg:my-0">
          <h1 className="text-3xl font-semibold leading-tight tracking-tight lg:text-4xl">
            From a worry to a tested rule. From an alert to a reviewed case.
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-white/80">
            Risk owners design and measure fan-pattern rules on labeled data. Analysts review AI-drafted case files
            where every number is checked against the facts. A human makes every decision.
          </p>
          <ul className="mt-6 space-y-2 text-sm text-white/85">
            {["Rules measured for precision and pattern recall before they run", "Case files cite facts and regulator guidance",
              "Evidence checker rejects unsupported numbers"].map((t) => (
              <li key={t} className="flex items-start gap-2"><Icon name="check" className="mt-0.5 h-4 w-4 shrink-0" />{t}</li>
            ))}
          </ul>
        </div>
        <p className="relative text-[11px] leading-relaxed text-white/60">
          Prototype on simulated public data (IBM AML HI-Small). Not a compliance system.
        </p>
      </div>

      {/* sign-in */}
      <div className="flex flex-1 items-center justify-center px-6 py-12">
        <div className="w-full max-w-md">
          <h2 className="text-2xl font-semibold tracking-tight text-slate-900">Sign in</h2>
          <p className="mt-1 text-sm text-slate-500">Choose a demo account or enter its credentials.</p>

          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            {DEMO_ACCOUNTS.map((a) => {
              const active = username.trim().toLowerCase() === a.username;
              return (
                <button key={a.username} type="button" onClick={() => { setUsername(a.username); setPassword(a.password); }}
                  className={cx("rounded-xl border p-4 text-left transition",
                    active ? "border-brand-600 bg-brand-50 ring-4 ring-brand-100" : "border-slate-200 hover:border-slate-300 hover:bg-slate-50")}>
                  <div className="flex items-center gap-2">
                    <span className={cx("grid h-8 w-8 place-items-center rounded-full text-sm font-semibold",
                      a.role === "owner" ? "bg-violet-100 text-violet-700" : "bg-emerald-100 text-emerald-700")}>
                      {a.username[0].toUpperCase()}
                    </span>
                    <div>
                      <div className="text-sm font-semibold text-slate-900">{a.title}</div>
                      <div className="font-mono text-[11px] text-slate-500">{a.username} / {a.password}</div>
                    </div>
                  </div>
                  <ul className="mt-3 space-y-1 text-xs text-slate-600">
                    {a.does.map((d) => <li key={d} className="flex gap-1.5"><span className="text-slate-400">•</span>{d}</li>)}
                  </ul>
                </button>
              );
            })}
          </div>

          <form className="mt-6 space-y-4" onSubmit={(e) => { e.preventDefault(); if (username.trim() && password) login.mutate(); }}>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">Username</span>
              <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus
                className="w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm shadow-sm focus:border-brand-600 focus:outline-none focus:ring-4 focus:ring-brand-100" />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">Password</span>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password"
                className="w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm shadow-sm focus:border-brand-600 focus:outline-none focus:ring-4 focus:ring-brand-100" />
            </label>
            {login.isError && <ErrorBox error={login.error} title="Could not sign in" />}
            <Button type="submit" className="w-full justify-center py-2.5" loading={login.isPending} disabled={!username.trim() || !password}>
              Sign in
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}

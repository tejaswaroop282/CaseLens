import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api/client";
import { useAnalyst } from "../lib/analyst";
import { cx, Icon, type IconName } from "./ui";

const NAV: { to: string; label: string; icon: IconName; hint: string }[] = [
  { to: "/scenarios", label: "Scenario Studio", icon: "studio", hint: "Turn a worry into a rule" },
  { to: "/alerts", label: "Alert queue", icon: "queue", hint: "Investigate and decide" },
];

export default function Layout() {
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: 60_000 });
  const [analyst, setAnalyst] = useAnalyst();
  return (
    <div className="flex min-h-full">
      <aside className="fixed inset-y-0 left-0 z-20 flex w-60 flex-col border-r border-slate-200 bg-white">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-brand-700 text-white shadow-sm">
            <svg viewBox="0 0 24 24" className="h-4.5 w-4.5" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
              <circle cx="10.5" cy="10.5" r="5.5" /><path d="m15 15 5 5" />
            </svg>
          </div>
          <div>
            <div className="text-[15px] font-semibold tracking-tight text-slate-900">CaseLens</div>
            <div className="text-[11px] text-slate-500">Fan-pattern review</div>
          </div>
        </div>
        <nav className="flex-1 space-y-1 px-3 py-2">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to}
              className={({ isActive }) => cx("group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
                isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900")}>
              <Icon name={n.icon} className="h-4.5 w-4.5" />
              <span className="flex-1">{n.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="m-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-[11px] leading-relaxed text-slate-500">
          <div className="mb-1 flex items-center gap-1.5 font-semibold text-slate-700"><Icon name="shield" className="h-3.5 w-3.5" />Prototype</div>
          Simulated public data (IBM AML {meta.data?.dataset ?? "HI-Small"}). AI drafts only; a human decides. Not a compliance system.
          {meta.data?.model_id && <div className="mt-2 font-mono text-[10px] text-slate-400">{meta.data.model_id} · {meta.data.prompt_version}</div>}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col pl-60">
        <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b border-slate-200 bg-white/85 px-8 backdrop-blur">
          <div className="text-xs text-slate-500">
            {meta.data?.data_loaded
              ? <>Data slice: <span className="font-medium text-slate-700">{meta.data.slice_hours} h</span> from {meta.data.data_origin?.slice(0, 10)}</>
              : meta.isError ? <span className="text-rose-600">API not reachable</span> : <span>No data loaded yet</span>}
          </div>
          <label className="flex items-center gap-2 text-sm">
            <span className="grid h-7 w-7 place-items-center rounded-full bg-slate-100 text-slate-500"><Icon name="user" className="h-4 w-4" /></span>
            <input value={analyst} onChange={(e) => setAnalyst(e.target.value)} placeholder="Your name (analyst)"
              aria-label="Analyst name"
              className="w-48 rounded-md border border-transparent bg-transparent px-2 py-1 text-sm text-slate-800 placeholder:text-slate-400 hover:border-slate-200 focus:border-brand-600 focus:outline-none" />
          </label>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-8 py-8"><Outlet /></main>
      </div>
    </div>
  );
}

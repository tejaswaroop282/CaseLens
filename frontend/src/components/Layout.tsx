import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { HOME, type Role, useAuth } from "../lib/auth";
import { cx, Icon, type IconName } from "./ui";

type NavItem = { to: string; label: string; icon: IconName; end?: boolean };

// Each role sees only its own work (D19). The server enforces the same split.
const NAV: Record<Role, { section: string; items: NavItem[] }[]> = {
  owner: [
    { section: "Workspace", items: [{ to: "/owner", label: "Overview", icon: "home", end: true }] },
    { section: "Rules", items: [{ to: "/scenarios", label: "Scenario Studio", icon: "studio" }] },
    { section: "Data", items: [{ to: "/data", label: "Upload transactions", icon: "database" }] },
  ],
  analyst: [
    { section: "Workspace", items: [{ to: "/analyst", label: "Overview", icon: "home", end: true }] },
    { section: "Cases", items: [{ to: "/alerts", label: "Alert queue", icon: "queue" }] },
  ],
};

export default function Layout() {
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: 60_000 });
  const { user, signOut } = useAuth();
  const qc = useQueryClient();
  const nav = useNavigate();
  if (!user) return null;
  const owner = user.role === "owner";

  return (
    <div className="flex min-h-full">
      <aside className="fixed inset-y-0 left-0 z-20 flex w-60 flex-col border-r border-slate-200 bg-white">
        <NavLink to={HOME[user.role]} className="flex items-center gap-2.5 px-5 py-5">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-brand-700 text-white shadow-sm">
            <svg viewBox="0 0 24 24" className="h-4.5 w-4.5" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
              <circle cx="10.5" cy="10.5" r="5.5" /><path d="m15 15 5 5" />
            </svg>
          </div>
          <div>
            <div className="text-[15px] font-semibold tracking-tight text-slate-900">CaseLens</div>
            <div className="text-[11px] text-slate-500">{owner ? "Risk owner workspace" : "Analyst workspace"}</div>
          </div>
        </NavLink>
        <nav className="flex-1 space-y-5 px-3 py-2">
          {NAV[user.role].map((g) => (
            <div key={g.section}>
              <div className="px-3 pb-1.5 text-[10.5px] font-semibold uppercase tracking-wider text-slate-400">{g.section}</div>
              <div className="space-y-1">
                {g.items.map((n) => (
                  <NavLink key={n.to} to={n.to} end={n.end}
                    className={({ isActive }) => cx("flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
                      isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900")}>
                    <Icon name={n.icon} className="h-4.5 w-4.5" />
                    <span className="flex-1">{n.label}</span>
                  </NavLink>
                ))}
              </div>
            </div>
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
              ? <>Data loaded: <span className="font-medium text-slate-700">{meta.data.slice_hours} h</span> from {meta.data.data_origin?.slice(0, 10)}</>
              : meta.isError ? <span className="text-rose-600">API not reachable</span> : <span>No data loaded yet</span>}
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2.5">
              <span className={cx("grid h-8 w-8 place-items-center rounded-full text-sm font-semibold",
                owner ? "bg-violet-100 text-violet-700" : "bg-emerald-100 text-emerald-700")}>{user.name[0]}</span>
              <div className="leading-tight">
                <div className="text-sm font-medium text-slate-900">{user.name}</div>
                <div className="text-[11px] text-slate-500">{user.role_label}</div>
              </div>
            </div>
            <button type="button" onClick={() => { signOut(); qc.clear(); nav("/login", { replace: true }); }}
              className="ml-2 inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900">
              <Icon name="logout" className="h-3.5 w-3.5" />Sign out
            </button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-8 py-8"><Outlet /></main>
      </div>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, cx, EmptyState, Icon, type IconName, Loading, PageHeader, Pill, StatusPill, Table } from "../components/ui";
import { useAuth } from "../lib/auth";
import { directionLabel, fmtDateTime, fmtPct, fmtWindow, verdictLabel } from "../lib/format";

function Stat({ label, value, note, tone = "slate", to }: { label: string; value: ReactNode; note?: string;
  tone?: "slate" | "blue" | "amber" | "green" | "violet"; to?: string }) {
  const ring = { slate: "", blue: "border-l-brand-600", amber: "border-l-amber-500", green: "border-l-emerald-500",
    violet: "border-l-violet-500" }[tone];
  const body = (
    <div className={cx("h-full rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition", tone !== "slate" && "border-l-4",
      ring, to && "hover:border-slate-300 hover:shadow-md")}>
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-3xl font-semibold tabular-nums text-slate-900">{value ?? "—"}</div>
      {note && <div className="mt-1 text-xs text-slate-500">{note}</div>}
    </div>
  );
  return to ? <Link to={to} className="block">{body}</Link> : body;
}

function Task({ icon, title, children, to, cta }: { icon: IconName; title: string; children: ReactNode; to: string; cta: string }) {
  return (
    <Link to={to} className="group flex gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-brand-100 hover:shadow-md">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-700"><Icon name={icon} className="h-5 w-5" /></span>
      <span className="flex-1">
        <span className="block text-sm font-semibold text-slate-900">{title}</span>
        <span className="mt-0.5 block text-sm text-slate-500">{children}</span>
        <span className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-brand-700 group-hover:underline">{cta} →</span>
      </span>
    </Link>
  );
}

// ---------------- risk owner ----------------
export function OwnerHome() {
  const { user } = useAuth();
  const sc = useQuery({ queryKey: ["scenarios"], queryFn: () => api.scenarios(1) });
  const alerts = useQuery({ queryKey: ["alerts", "", "", 1], queryFn: () => api.alerts({ page: 1 }) });
  const counts = useQuery({ queryKey: ["decision-counts", ""], queryFn: () => api.decisionCounts() });
  const items = sc.data?.items ?? [];
  const drafts = items.filter((s) => s.status === "draft" && s.spec.direction);
  const live = items.filter((s) => s.latest_run?.status === "completed" && s.latest_run.metrics);
  const decided = counts.data ? counts.data.dismiss + counts.data.escalate + counts.data.need_info : undefined;

  return (
    <>
      <PageHeader eyebrow="Risk owner workspace" title={`Welcome back, ${user?.name}`}
        subtitle="Design fan-pattern rules, measure them on labeled data before they go live, and feed in new transactions." />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Drafts to approve" value={sc.data ? drafts.length : undefined} tone={drafts.length ? "amber" : "slate"}
          note="AI-drafted rules waiting for you" to="/scenarios" />
        <Stat label="Rules in use" value={sc.data ? live.length : undefined} tone="blue" note="Approved and run" to="/scenarios" />
        <Stat label="Alerts raised" value={alerts.data?.total.toLocaleString("en-US")} tone="violet" note="Across all rules" />
        <Stat label="Analyst decisions" value={decided} tone="green"
          note={counts.data ? `${counts.data.escalate} escalated · ${counts.data.dismiss} dismissed · ${counts.data.need_info} need info` : undefined} />
      </div>

      <h2 className="mb-3 mt-8 text-sm font-semibold uppercase tracking-wide text-slate-500">Your tasks</h2>
      <div className="grid gap-4 lg:grid-cols-3">
        <Task icon="spark" title="Turn a worry into a rule" to="/scenarios" cta="Open Scenario Studio">
          Describe what worries you in plain English; the AI drafts a fan-pattern rule for you to check.
        </Task>
        <Task icon="check" title={drafts.length ? `Review ${drafts.length} draft${drafts.length > 1 ? "s" : ""}` : "Approve and run rules"}
          to={drafts[0] ? `/scenarios/${drafts[0].scenario_id}` : "/scenarios"} cta={drafts.length ? "Review the next draft" : "See all rules"}>
          Nothing runs until you approve it. Each run reports precision and pattern recall on labeled data.
        </Task>
        <Task icon="upload" title="Add new transactions" to="/data" cta="Open Data">
          Upload a file in the IBM format, check it, append it, and run approved rules on the new windows only.
        </Task>
      </div>

      <div className="mt-8">
        <Card title="Rule performance" subtitle="Latest run of each rule, measured on the labeled slice" padded={false}>
          {sc.isLoading ? <Loading /> : !live.length
            ? <EmptyState icon="studio" title="No rules have run yet">Approve a draft and run it to see its numbers here.</EmptyState>
            : (
              <Table head={["Rule", "Pattern", "Alerts", "Precision", "Pattern recall", "Approved by", "Last run"]}>
                {live.map((s) => {
                  const m = s.latest_run!.metrics!;
                  return (
                    <tr key={s.scenario_id} className="hover:bg-slate-50/70">
                      <td className="max-w-sm px-4 py-3">
                        <Link to={`/scenarios/${s.scenario_id}`} className="font-medium text-slate-800 hover:text-brand-700">
                          ≥ {s.spec.params?.min_counterparties} counterparties / {s.spec.params?.window_hours} h
                        </Link>
                        <div className="line-clamp-1 text-xs text-slate-500">{s.intent_text}</div>
                      </td>
                      <td className="px-4 py-3"><Pill tone="blue">{directionLabel(s.spec.direction)}</Pill></td>
                      <td className="px-4 py-3 tabular-nums">{m.alert_count.toLocaleString("en-US")}</td>
                      <td className="px-4 py-3 tabular-nums">{fmtPct(m.alert_precision)}</td>
                      <td className="px-4 py-3 tabular-nums">{fmtPct(m.pattern_recall.recall)}
                        <span className="text-slate-400"> ({m.pattern_recall.caught}/{m.pattern_recall.total})</span></td>
                      <td className="px-4 py-3 text-slate-600">{s.approved_by ?? "—"}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-slate-500">{fmtDateTime(s.latest_run!.finished_at)}</td>
                    </tr>
                  );
                })}
              </Table>
            )}
        </Card>
      </div>
    </>
  );
}

// ---------------- analyst ----------------
export function AnalystHome() {
  const { user } = useAuth();
  const fresh = useQuery({ queryKey: ["alerts", "", "new", 1], queryFn: () => api.alerts({ status: "new", page: 1 }) });
  const open = useQuery({ queryKey: ["alerts", "", "investigating", "all"],
    queryFn: () => api.alerts({ status: "investigating", page: 1, pageSize: 200 }) });
  const done = useQuery({ queryKey: ["alerts", "", "reviewed", 1], queryFn: () => api.alerts({ status: "reviewed", page: 1 }) });
  const counts = useQuery({ queryKey: ["decision-counts", ""], queryFn: () => api.decisionCounts() });
  const ready = (open.data?.items ?? []).filter((a) => a.latest_case && ["checked", "needs_human_rewrite", "failed"].includes(a.latest_case.status));

  return (
    <>
      <PageHeader eyebrow="Analyst workspace" title={`Welcome back, ${user?.name}`}
        subtitle="Work the alert queue. Investigate an alert to get an AI-drafted case file with checked evidence, then make the call." />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Ready for your decision" value={open.data ? ready.length : undefined} tone={ready.length ? "amber" : "slate"}
          note="Case file drafted and checked" />
        <Stat label="New alerts" value={fresh.data?.total.toLocaleString("en-US")} tone="blue" note="Not investigated yet" to="/alerts?status=new" />
        <Stat label="Reviewed" value={done.data?.total.toLocaleString("en-US")} tone="green" note="Decision recorded" to="/alerts?status=reviewed" />
        <Stat label="Escalated" value={counts.data?.escalate} tone="violet"
          note={counts.data ? `${counts.data.dismiss} dismissed · ${counts.data.need_info} need info` : undefined} />
      </div>

      <div className="mt-8 grid gap-4 lg:grid-cols-2">
        <Task icon="queue" title="Work the alert queue" to="/alerts?status=new" cta="Open new alerts">
          Pick an alert and click Investigate. Code builds the facts; AI drafts the case file; a checker verifies every number.
        </Task>
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-sm font-semibold text-slate-900">How decisions work</div>
          <div className="mt-2 grid gap-1.5 text-sm text-slate-600 sm:grid-cols-3">
            <span><span className="font-medium text-emerald-700">Dismiss</span> — false alarm</span>
            <span><span className="font-medium text-rose-700">Escalate</span> — investigate further</span>
            <span><span className="font-medium text-amber-700">Need info</span> — more evidence</span>
          </div>
          <p className="mt-3 text-xs text-slate-500">Every decision needs a reason, is recorded under your name and cannot be changed. The AI never decides.</p>
        </div>
      </div>

      <div className="mt-6">
        <Card title="Ready for your decision" subtitle="Investigations that finished and wait for a human" padded={false}
          action={ready.length > 10 ? <Link to="/alerts?status=investigating" className="text-sm font-medium text-brand-700 hover:underline">All {ready.length} →</Link> : undefined}>
          {open.isLoading ? <Loading /> : !ready.length
            ? <EmptyState icon="inbox" title="Nothing waiting">Open the alert queue and investigate an alert to start a case.</EmptyState>
            : (
              <Table head={["Account", "Pattern", "Window", "Counterparties", "AI view", ""]}>
                {ready.slice(0, 10).map((a) => (
                  <tr key={a.alert_id} className="hover:bg-slate-50/70">
                    <td className="px-4 py-3 font-mono text-xs text-slate-700">{a.account_id}</td>
                    <td className="px-4 py-3"><Pill tone="blue">{directionLabel(a.direction)}</Pill></td>
                    <td className="whitespace-nowrap px-4 py-3 text-slate-600">{fmtWindow(a.window_start, a.window_end)}</td>
                    <td className="px-4 py-3 tabular-nums">{a.distinct_counterparties.toLocaleString("en-US")}</td>
                    <td className="px-4 py-3">{a.latest_case?.verdict ? <Pill tone="amber">{verdictLabel[a.latest_case.verdict]}</Pill>
                      : <StatusPill status={a.latest_case!.status} />}</td>
                    <td className="px-4 py-3 text-right">
                      <Link to={`/cases/${a.latest_case!.case_id}`} className="whitespace-nowrap text-sm font-medium text-brand-700 hover:underline">Review →</Link>
                    </td>
                  </tr>
                ))}
              </Table>
            )}
        </Card>
      </div>
    </>
  );
}

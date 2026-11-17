import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Alert } from "../api/types";
import { Button, Card, EmptyState, ErrorBox, Icon, Loading, PageHeader, Pill, StatusPill, Table } from "../components/ui";
import { directionLabel, fmtWindow, verdictLabel } from "../lib/format";

export default function AlertsPage() {
  const [params, setParams] = useSearchParams();
  const scenarioId = params.get("scenario_id") ?? "";
  const status = params.get("status") ?? "";
  const page = Number(params.get("page") ?? 1);
  const set = (k: string, v: string) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v); else p.delete(k);
    if (k !== "page") p.delete("page");
    setParams(p);
  };

  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: () => api.scenarios(1) });
  const counts = useQuery({ queryKey: ["decision-counts", scenarioId], queryFn: () => api.decisionCounts(scenarioId || undefined) });
  const q = useQuery({
    queryKey: ["alerts", scenarioId, status, page],
    queryFn: () => api.alerts({ scenario_id: scenarioId || undefined, status: status || undefined, page }),
    refetchInterval: (query) => (query.state.data?.items.some((a) => a.latest_case &&
      ["queued", "running"].includes(a.latest_case.status)) ? 3000 : false),
  });
  const ran = (scenarios.data?.items ?? []).filter((s) => s.status === "completed");
  const totalPages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1;

  return (
    <>
      <PageHeader title="Alert queue"
        subtitle="Alerts raised by approved fan-pattern scenarios. Investigate one to get an AI-drafted case file; you make the decision."
        actions={counts.data && (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-slate-500">Decided:</span>
            <Pill tone="green">{counts.data.dismiss} dismissed</Pill>
            <Pill tone="red">{counts.data.escalate} escalated</Pill>
            <Pill tone="amber">{counts.data.need_info} need info</Pill>
          </div>
        )} />

      <Card padded={false}
        title={<span>{q.data ? `${q.data.total.toLocaleString("en-US")} alerts` : "Alerts"}</span>}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <select value={scenarioId} onChange={(e) => set("scenario_id", e.target.value)}
              className="max-w-xs rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-brand-600 focus:outline-none">
              <option value="">All scenarios</option>
              {ran.map((s) => <option key={s.scenario_id} value={s.scenario_id}>{s.intent_text.slice(0, 60)}</option>)}
            </select>
            <select value={status} onChange={(e) => set("status", e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-brand-600 focus:outline-none">
              <option value="">Any status</option>
              <option value="new">New</option>
              <option value="investigating">Investigating</option>
              <option value="reviewed">Reviewed</option>
            </select>
          </div>
        }>
        {q.isLoading ? <Loading /> : q.isError ? <div className="p-5"><ErrorBox error={q.error} /></div>
          : !q.data?.items.length ? (
            <EmptyState icon="queue" title="No alerts here">Alerts appear when the risk owner runs an approved rule.</EmptyState>
          ) : (
            <>
              <Table head={["Account", "Pattern", "Window", "Counterparties", "Transactions", "Status", "Case", ""]}>
                {q.data.items.map((a) => <AlertRow key={a.alert_id} alert={a} />)}
              </Table>
              <div className="flex items-center justify-between border-t border-slate-100 px-5 py-3 text-sm text-slate-500">
                <span>Page {page} of {totalPages}</span>
                <div className="flex gap-2">
                  <Button variant="secondary" disabled={page <= 1} onClick={() => set("page", String(page - 1))}>Previous</Button>
                  <Button variant="secondary" disabled={page >= totalPages} onClick={() => set("page", String(page + 1))}>Next</Button>
                </div>
              </div>
            </>
          )}
      </Card>
    </>
  );
}

function AlertRow({ alert: a }: { alert: Alert }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const inv = useMutation({
    mutationFn: () => api.investigate(a.alert_id),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["alerts"] }); nav(`/cases/${r.case_id}`); },
  });
  const c = a.latest_case;
  const active = c && ["queued", "running"].includes(c.status);
  return (
    <tr className={c ? "cursor-pointer hover:bg-slate-50/70" : "hover:bg-slate-50/40"}
      onClick={() => c && nav(`/cases/${c.case_id}`)}>
      <td className="px-4 py-3 font-mono text-xs text-slate-700">{a.account_id}</td>
      <td className="px-4 py-3"><Pill tone="blue">{directionLabel(a.direction)}</Pill></td>
      <td className="whitespace-nowrap px-4 py-3 text-slate-600">{fmtWindow(a.window_start, a.window_end)}</td>
      <td className="px-4 py-3 font-medium tabular-nums">{a.distinct_counterparties.toLocaleString("en-US")}</td>
      <td className="px-4 py-3 tabular-nums text-slate-600">{a.tx_count.toLocaleString("en-US")}</td>
      <td className="px-4 py-3"><StatusPill status={a.status} /></td>
      <td className="px-4 py-3">
        {c ? <div className="flex flex-col gap-1"><StatusPill status={c.status} />
          {c.verdict && <span className="text-xs text-slate-500">AI: {verdictLabel[c.verdict]}</span>}</div>
          : <span className="text-xs text-slate-400">—</span>}
      </td>
      <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
        {inv.isError && <span className="mr-2 text-xs text-rose-600">{(inv.error as Error).message}</span>}
        {a.status !== "reviewed" && !active && (
          <Button variant={c ? "secondary" : "primary"} loading={inv.isPending} onClick={() => inv.mutate()} className="whitespace-nowrap">
            <Icon name="spark" />{c ? "Re-investigate" : "Investigate"}
          </Button>
        )}
      </td>
    </tr>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { Meta, RunMode, Scenario } from "../api/types";
import { fmtDateTime, fmtPct } from "../lib/format";
import { Button, Card, cx, ErrorBox, Icon, Pill, StatusPill, Table } from "./ui";

const MODES: { m: RunMode; label: string; hint: string }[] = [
  { m: "all", label: "All data", hint: "Every complete window in the loaded data" },
  { m: "range", label: "Date range", hint: "e.g. design on day 1, validate on day 2" },
  { m: "new", label: "New data only", hint: "Windows after the last run" },
];

const day = (iso: string | null | undefined) => (iso ? iso.slice(0, 10) : "");

/** Run controls: approved scenarios get their first run; completed ones can run on a range or on new data (D17). */
export function RunPanel({ scenario, meta }: { scenario: Scenario; meta?: Meta }) {
  const first = scenario.status === "approved";
  const [mode, setMode] = useState<RunMode>("all");
  const [from, setFrom] = useState(day(meta?.data_origin));
  const [to, setTo] = useState(day(meta?.slice_end));
  const qc = useQueryClient();
  const run = useMutation({
    mutationFn: () => api.run(scenario.scenario_id, mode === "range"
      ? { mode, start: `${from}T00:00:00Z`, end: `${to}T00:00:00Z` } : { mode }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["scenario", scenario.scenario_id] });
      qc.invalidateQueries({ queryKey: ["runs", scenario.scenario_id] }); },
  });
  if (!["approved", "completed"].includes(scenario.status)) return null;
  const options = first ? MODES.filter((o) => o.m !== "new") : MODES;
  return (
    <Card title={first ? "Run the rule" : "Run again"}
      subtitle={first ? "Choose which data to run the approved rule on." :
        `Covered up to ${fmtDateTime(scenario.covered_until)} · data loaded up to ${fmtDateTime(meta?.slice_end)}`}>
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">Data</div>
          <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-1">
            {options.map((o) => (
              <button key={o.m} type="button" title={o.hint} onClick={() => setMode(o.m)}
                className={cx("rounded-md px-3 py-1.5 text-sm font-medium transition",
                  mode === o.m ? "bg-white text-brand-700 shadow-sm ring-1 ring-slate-200" : "text-slate-500 hover:text-slate-800")}>
                {o.label}
              </button>
            ))}
          </div>
        </div>
        {mode === "range" && (
          <div className="flex items-end gap-2">
            {([["From (UTC)", from, setFrom], ["To (UTC, exclusive)", to, setTo]] as const).map(([l, v, set]) => (
              <label key={l} className="block">
                <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">{l}</span>
                <input type="date" value={v} onChange={(e) => set(e.target.value)} min={day(meta?.data_origin)}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm shadow-sm focus:border-brand-600 focus:outline-none" />
              </label>
            ))}
          </div>
        )}
        <Button onClick={() => run.mutate()} loading={run.isPending} disabled={mode === "range" && (!from || !to || from >= to)}>
          <Icon name="play" />Run
        </Button>
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Only complete {scenario.spec.params?.window_hours}-hour windows are evaluated. Alerts that already exist are never created twice.
      </p>
      {run.isError && <div className="mt-3"><ErrorBox error={run.error} title="Run not started" /></div>}
    </Card>
  );
}

export function RunHistory({ scenarioId, refreshKey }: { scenarioId: string; refreshKey?: string }) {
  const q = useQuery({ queryKey: ["runs", scenarioId, refreshKey], queryFn: () => api.runs(scenarioId) });
  const items = q.data?.items ?? [];
  if (items.length < 2) return null;                              // a single run is already shown in the cards above
  return (
    <Card title="Run history" subtitle="Compare periods: a rule that holds up on data it was not designed on is more trustworthy." padded={false}>
      <Table head={["Started", "Data", "Period", "Alerts (new)", "Precision", "Pattern recall", "Status"]}>
        {items.map((r) => (
          <tr key={r.run_id}>
            <td className="whitespace-nowrap px-4 py-3 text-slate-600">{fmtDateTime(r.started_at)}</td>
            <td className="px-4 py-3"><Pill tone="slate">{r.mode === "new" ? "New data" : r.mode === "range" ? "Range" : "All data"}</Pill></td>
            <td className="whitespace-nowrap px-4 py-3 text-slate-600">{fmtDateTime(r.range_start)} → {fmtDateTime(r.range_end)}</td>
            <td className="px-4 py-3 tabular-nums">{r.metrics ? <>{r.metrics.alert_count} <span className="text-slate-400">({r.metrics.new_alerts ?? r.metrics.alert_count})</span></> : "—"}</td>
            <td className="px-4 py-3 tabular-nums">{fmtPct(r.metrics?.alert_precision)}</td>
            <td className="px-4 py-3 tabular-nums">{r.metrics ? `${fmtPct(r.metrics.pattern_recall.recall)} (${r.metrics.pattern_recall.caught}/${r.metrics.pattern_recall.total})` : "—"}</td>
            <td className="px-4 py-3"><StatusPill status={r.status} /></td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}

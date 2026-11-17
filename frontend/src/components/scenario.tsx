import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Direction, ExampleItem, Meta, RuleRun, Scenario } from "../api/types";
import { directionLabel, fmtDateTime, fmtPct, fmtWindow } from "../lib/format";
import { Button, Callout, Card, cx, EmptyState, ErrorBox, Icon, Loading, Pill, Spinner, Table } from "./ui";

// ---------------- SpecEditor ----------------
export function SpecEditor({ scenario, meta }: { scenario: Scenario; meta?: Meta }) {
  const { spec, status } = scenario;
  const editable = status === "draft" && spec.direction !== null;
  const [direction, setDirection] = useState<Direction | null>(spec.direction);
  const [minCp, setMinCp] = useState(spec.params?.min_counterparties ?? 10);
  const [windowH, setWindowH] = useState(spec.params?.window_hours ?? 24);
  const [formats, setFormats] = useState<string[]>(spec.params?.payment_formats ?? []);
  const qc = useQueryClient();
  const nav = useNavigate();

  useEffect(() => {
    setDirection(spec.direction); setMinCp(spec.params?.min_counterparties ?? 10);
    setWindowH(spec.params?.window_hours ?? 24); setFormats(spec.params?.payment_formats ?? []);
  }, [scenario.scenario_id, spec]);

  const dirty = editable && (direction !== spec.direction || minCp !== spec.params?.min_counterparties ||
    windowH !== spec.params?.window_hours || JSON.stringify(formats) !== JSON.stringify(spec.params?.payment_formats ?? []));
  const refresh = () => qc.invalidateQueries({ queryKey: ["scenario", scenario.scenario_id] });

  const save = useMutation({
    mutationFn: () => api.patch(scenario.scenario_id, { direction: direction ?? undefined,
      params: { min_counterparties: minCp, window_hours: windowH, payment_formats: formats.length ? formats : null } }),
    onSuccess: refresh,
  });
  const approve = useMutation({ mutationFn: () => api.approve(scenario.scenario_id), onSuccess: refresh });
  const clone = useMutation({ mutationFn: () => api.clone(scenario.scenario_id),
    onSuccess: (s) => { qc.invalidateQueries({ queryKey: ["scenarios"] }); nav(`/scenarios/${s.scenario_id}`); } });
  const busy = save.isPending || approve.isPending || clone.isPending;
  const problems = scenario.validation_problems ?? [];
  const maxWindow = meta?.slice_hours ?? 240;

  return (
    <Card title="Scenario" subtitle={editable ? "Draft — review and adjust the numbers, then approve." : "Read-only"}
      action={<Pill tone={spec.direction ? "blue" : "amber"}>{directionLabel(spec.direction)}</Pill>}>
      {spec.direction === null ? (
        <Callout tone="amber" icon="alert" title="Unsupported worry — this cannot be approved">
          {spec.unsupported_reason} CaseLens only supports the fan pattern. Write a new worry instead.
        </Callout>
      ) : (
        <div className="space-y-5">
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Direction</label>
            <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-1">
              {(["out", "in"] as const).map((d) => (
                <button key={d} type="button" disabled={!editable} onClick={() => setDirection(d)}
                  className={cx("rounded-md px-3.5 py-1.5 text-sm font-medium transition disabled:cursor-default",
                    direction === d ? "bg-white text-brand-700 shadow-sm ring-1 ring-slate-200" : "text-slate-500 hover:text-slate-800")}>
                  {d === "out" ? "Fan-out · one pays many" : "Fan-in · many pay one"}
                </button>
              ))}
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <NumberField label="Minimum distinct counterparties" value={minCp} min={3} max={200} disabled={!editable} onChange={setMinCp} suffix="accounts" />
            <NumberField label="Window length" value={windowH} min={1} max={maxWindow} disabled={!editable} onChange={setWindowH}
              suffix="hours" hint={meta?.slice_hours ? `At most ${meta.slice_hours} h (the loaded data slice).` : undefined} />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Payment formats</label>
            <div className="flex flex-wrap gap-2">
              {(meta?.payment_formats ?? formats).map((f) => {
                const on = formats.includes(f);
                return (
                  <button key={f} type="button" disabled={!editable}
                    onClick={() => setFormats(on ? formats.filter((x) => x !== f) : [...formats, f])}
                    className={cx("rounded-full border px-3 py-1 text-xs font-medium transition disabled:cursor-default",
                      on ? "border-brand-600 bg-brand-50 text-brand-700" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300")}>
                    {on && <Icon name="check" className="mr-1 inline h-3 w-3" />}{f}
                  </button>
                );
              })}
            </div>
            <p className="mt-1.5 text-xs text-slate-500">{formats.length ? "Only these formats are counted." : "None selected: all formats are counted."}</p>
          </div>
          {spec.legitimate_lookalikes.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">Harmless look-alikes to expect</div>
              <div className="flex flex-wrap gap-1.5">{spec.legitimate_lookalikes.map((l) => <Pill key={l}>{l}</Pill>)}</div>
            </div>
          )}
          {spec.rationale && (
            <div className="rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-600">
              <span className="font-medium text-slate-800">AI rationale: </span>{spec.rationale}
            </div>
          )}
          {problems.map((p) => <Callout key={p.code} tone="amber" icon="alert" title="Fix before approving">{p.message}</Callout>)}
        </div>
      )}

      {[save, approve, clone].map((m, i) => m.isError && <div key={i} className="mt-4"><ErrorBox error={m.error} /></div>)}

      <div className="mt-6 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4">
        {editable && <Button variant="secondary" onClick={() => save.mutate()} disabled={!dirty || busy} loading={save.isPending}>Save changes</Button>}
        {status === "draft" && spec.direction && (
          <Button onClick={() => approve.mutate()} disabled={busy || dirty || problems.length > 0} loading={approve.isPending}
            title="Approve as the signed-in risk owner">
            <Icon name="check" />Approve
          </Button>
        )}
        <Button variant="ghost" onClick={() => clone.mutate()} disabled={busy} loading={clone.isPending}><Icon name="copy" />Clone</Button>
        {scenario.approved_by && <span className="ml-auto text-xs text-slate-500">Approved by {scenario.approved_by} · {fmtDateTime(scenario.approved_at)}</span>}
      </div>
    </Card>
  );
}

function NumberField({ label, value, onChange, min, max, disabled, suffix, hint }: {
  label: string; value: number; onChange: (v: number) => void; min: number; max: number; disabled: boolean; suffix: string; hint?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
      <div className="flex items-center rounded-lg border border-slate-300 bg-white shadow-sm focus-within:border-brand-600 focus-within:ring-4 focus-within:ring-brand-100">
        <input type="number" min={min} max={max} value={value} disabled={disabled}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full rounded-l-lg bg-transparent px-3 py-2 text-sm tabular-nums text-slate-900 focus:outline-none disabled:text-slate-500" />
        <span className="pr-3 text-xs text-slate-400">{suffix}</span>
      </div>
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

// ---------------- RunStatus + MetricsCards ----------------
export function RunStatus({ run }: { run: RuleRun | null | undefined }) {
  if (!run) return null;
  if (run.status === "running") return (
    <Callout tone="blue" icon="info" title={<span className="inline-flex items-center gap-2"><Spinner className="h-4 w-4" />Running the rule on the data…</span>}>
      Started {fmtDateTime(run.started_at)}. This page updates automatically.
    </Callout>
  );
  if (run.status === "failed") return (
    <Callout tone="red" icon="alert" title={run.error?.code === "too_many_alerts" ? "Too many alerts — tighten the numbers" : "The run failed"}>
      {run.error?.message} {run.error?.code === "too_many_alerts" && "Clone the scenario and raise the counterparty minimum or shorten the window."}
    </Callout>
  );
  return null;
}

export function MetricsCards({ run, scenarioId }: { run: RuleRun; scenarioId: string }) {
  const m = run.metrics!;
  // hours actually evaluated: only complete windows count, so this can be less than the loaded slice
  const evaluated = run.range_start && run.range_end
    ? Math.round((Date.parse(run.range_end) - Date.parse(run.range_start)) / 3_600_000) : m.slice_hours;
  const cards = [
    { label: "Alerts", value: m.alert_count.toLocaleString("en-US"),
      note: `in ${evaluated} h evaluated${evaluated !== m.slice_hours ? ` (of ${m.slice_hours} h loaded)` : ""} · ${m.duration_seconds.toFixed(1)} s` },
    { label: "Precision", value: fmtPct(m.alert_precision), note: `${m.suspicious_alert_count} alerts contain laundering-labeled transactions` },
    { label: "False alarms", value: m.false_alarm_count.toLocaleString("en-US"), note: "alerts with no labeled transaction" },
    { label: "Pattern recall", value: fmtPct(m.pattern_recall.recall),
      note: `${m.pattern_recall.caught} of ${m.pattern_recall.total} labeled ${m.pattern_type.replace("_", "-")} blocks touched` },
  ];
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((c) => (
          <div key={c.label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{c.label}</div>
            <div className="mt-2 text-2xl font-semibold tabular-nums tracking-tight text-slate-900">{c.value}</div>
            <div className="mt-1 text-xs text-slate-500">{c.note}</div>
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
        <span>Measured on the labeled slice. An alert counts as suspicious if any of its transactions is labeled laundering.</span>
        <Link to={`/alerts?scenario_id=${scenarioId}`} className="font-medium text-brand-700 hover:underline">Open these alerts in the queue →</Link>
      </div>
    </div>
  );
}

// ---------------- ExamplesTable ----------------
export function ExamplesTable({ scenarioId }: { scenarioId: string }) {
  const [tab, setTab] = useState<"hits" | "look_alikes">("hits");
  const q = useQuery({ queryKey: ["examples", scenarioId], queryFn: () => api.examples(scenarioId, 5) });
  const rows: ExampleItem[] = q.data?.[tab] ?? [];
  return (
    <Card title="Real examples" padded={false}
      subtitle="Real examples from the public dataset. The dataset is simulated. This view shows ground truth; case review never does."
      action={
        <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-xs">
          {([["hits", "Hits"], ["look_alikes", "Look-alikes"]] as const).map(([k, l]) => (
            <button key={k} onClick={() => setTab(k)}
              className={cx("rounded-md px-3 py-1.5 font-medium", tab === k ? "bg-white text-slate-900 shadow-sm" : "text-slate-500")}>
              {l} {q.data && <span className="ml-1 text-slate-400">{q.data[k].length}</span>}
            </button>
          ))}
        </div>
      }>
      {q.isLoading ? <Loading /> : q.isError ? <div className="p-5"><ErrorBox error={q.error} /></div>
        : rows.length === 0 ? <EmptyState title={tab === "hits" ? "No hits in this run" : "No look-alikes in this run"} />
        : (
          <Table head={["Account", "Window", "Counterparties", "Transactions", "Ground truth"]}>
            {rows.map((r) => (
              <tr key={r.alert_id}>
                <td className="px-4 py-3 font-mono text-xs text-slate-700">{r.account_id}</td>
                <td className="whitespace-nowrap px-4 py-3 text-slate-600">{fmtWindow(r.window_start, r.window_end)}</td>
                <td className="px-4 py-3 tabular-nums">{r.distinct_counterparties}</td>
                <td className="px-4 py-3 tabular-nums">{r.tx_count}</td>
                <td className="px-4 py-3">
                  {r.is_suspicious
                    ? <Pill tone="red">{r.n_laundering_tx} labeled tx{r.pattern_types.length ? ` · ${r.pattern_types.join(", ")}` : ""}</Pill>
                    : <Pill tone="green">No labeled tx</Pill>}
                </td>
              </tr>
            ))}
          </Table>
        )}
    </Card>
  );
}

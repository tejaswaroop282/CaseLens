import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Button, Card, EmptyState, ErrorBox, Icon, Loading, PageHeader, Pill, StatusPill, Table } from "../components/ui";
import { directionLabel, fmtDateTime } from "../lib/format";

const SAMPLES = [
  "Flag accounts that receive money from at least 20 different accounts within 12 hours.",
  "Alert me when one account pays 15 or more different accounts within 6 hours.",
  "Accounts that pay at least 10 different accounts within a day using wire payments only.",
];
const MAX = 1000;

function IntentForm() {
  const [text, setText] = useState("");
  const nav = useNavigate();
  const qc = useQueryClient();
  const parse = useMutation({
    mutationFn: () => api.parse(text),
    onSuccess: (s) => { qc.invalidateQueries({ queryKey: ["scenarios"] }); nav(`/scenarios/${s.scenario_id}`); },
  });
  const tooLong = text.length > MAX;
  return (
    <Card title="Describe a worry" subtitle="Plain English. The AI drafts a structured scenario; you review and approve it before anything runs.">
      <form onSubmit={(e) => { e.preventDefault(); if (text.trim() && !tooLong) parse.mutate(); }} className="space-y-3">
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={4}
          placeholder="e.g. I'm worried about accounts that suddenly receive money from many different senders in a single day."
          className="w-full resize-y rounded-lg border border-slate-300 bg-white px-3.5 py-3 text-sm leading-relaxed shadow-sm placeholder:text-slate-400 focus:border-brand-600 focus:outline-none focus:ring-4 focus:ring-brand-100" />
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-slate-500">Try:</span>
          {SAMPLES.map((s) => (
            <button type="button" key={s} onClick={() => setText(s)}
              className="max-w-xs truncate rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-600 hover:border-brand-100 hover:bg-brand-50 hover:text-brand-700">
              {s}
            </button>
          ))}
        </div>
        {parse.isError && <ErrorBox error={parse.error} title="Could not draft a scenario" />}
        <div className="flex items-center justify-between border-t border-slate-100 pt-3">
          <span className={tooLong ? "text-xs font-medium text-rose-600" : "text-xs text-slate-400"}>{text.length} / {MAX}</span>
          <Button type="submit" loading={parse.isPending} disabled={!text.trim() || tooLong}>
            <Icon name="spark" />Draft scenario
          </Button>
        </div>
      </form>
    </Card>
  );
}

export default function ScenariosPage() {
  const q = useQuery({ queryKey: ["scenarios"], queryFn: () => api.scenarios(1) });
  return (
    <>
      <PageHeader title="Scenario Studio"
        subtitle="CaseLens supports one pattern: the fan pattern — one account versus many different counterparties in a time window. Any other worry is rejected as unsupported." />
      <div className="grid gap-6 lg:grid-cols-5">
        <div className="lg:col-span-3"><IntentForm /></div>
        <div className="lg:col-span-2">
          <Card title="How it works">
            <ol className="space-y-3 text-sm text-slate-600">
              {[["Describe", "Write the worry in your own words."], ["Review", "Check the direction and numbers the AI drafted. Edit them if needed."],
                ["Approve & run", "The rule runs on a labeled slice of public, simulated data."],
                ["Learn", "See precision, pattern recall, and real hits and look-alikes."]].map(([t, d], i) => (
                <li key={t} className="flex gap-3">
                  <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand-50 text-xs font-semibold text-brand-700">{i + 1}</span>
                  <span><span className="font-medium text-slate-900">{t}.</span> {d}</span>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      </div>

      <div className="mt-6">
        <Card title="Scenarios" subtitle="Newest first" padded={false}>
          {q.isLoading ? <Loading /> : q.isError ? <div className="p-5"><ErrorBox error={q.error} /></div>
            : !q.data?.items.length ? <EmptyState icon="studio" title="No scenarios yet">Describe a worry above to create the first one.</EmptyState>
            : (
              <Table head={["Worry", "Pattern", "Rule", "Status", "Created"]}>
                {q.data.items.map((s) => (
                  <tr key={s.scenario_id} className="hover:bg-slate-50/70">
                    <td className="max-w-md px-4 py-3">
                      <Link to={`/scenarios/${s.scenario_id}`} className="line-clamp-2 font-medium text-slate-800 hover:text-brand-700">{s.intent_text}</Link>
                    </td>
                    <td className="px-4 py-3">
                      <Pill tone={s.spec.direction ? "blue" : "amber"}>{directionLabel(s.spec.direction)}</Pill>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-slate-600">
                      {s.spec.params ? <>≥ {s.spec.params.min_counterparties} counterparties / {s.spec.params.window_hours} h</> : "—"}
                    </td>
                    <td className="px-4 py-3"><StatusPill status={s.status} /></td>
                    <td className="whitespace-nowrap px-4 py-3 text-slate-500">{fmtDateTime(s.created_at)}</td>
                  </tr>
                ))}
              </Table>
            )}
        </Card>
      </div>
    </>
  );
}

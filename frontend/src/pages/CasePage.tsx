import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Fact } from "../api/types";
import { AiBanner, CheckerBadge, ClaimList, DecisionBar, EvidenceDrawer, FactTable, NeedsRewrite, type Evidence } from "../components/case";
import { Callout, Card, ErrorBox, Icon, Loading, PageHeader, Pill, Spinner, StatusPill } from "../components/ui";
import { directionLabel, fmtWindow, verdictLabel } from "../lib/format";

const verdictTone = { likely_legitimate: "green", needs_review: "amber", likely_suspicious: "red" } as const;

export default function CasePage() {
  const { caseId = "" } = useParams();
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const q = useQuery({
    queryKey: ["case", caseId], queryFn: () => api.case(caseId),
    refetchInterval: (query) => (["queued", "running"].includes(query.state.data?.status ?? "") ? 2000 : false),
  });
  const facts = useMemo(() => Object.fromEntries((q.data?.facts ?? []).map((f) => [f.id, f])) as Record<string, Fact>, [q.data]);
  const cited = useMemo(() => new Set((q.data?.case_file?.claims ?? []).flatMap((c) => c.fact_ids)), [q.data]);

  if (q.isLoading) return <Loading />;
  if (q.isError || !q.data) return <ErrorBox error={q.error} title="Could not load the case" />;
  const c = q.data;
  const a = c.alert;
  const cf = c.case_file;
  const working = c.status === "queued" || c.status === "running";

  return (
    <div className="pb-48">
      <Link to={a ? `/alerts?scenario_id=${a.scenario_id}` : "/alerts"} className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <Icon name="arrow-left" />Alert queue
      </Link>
      <PageHeader eyebrow={<>Case · {c.case_id.slice(0, 8)}</>}
        title={a ? <span className="flex flex-wrap items-center gap-3">
          <span className="font-mono">{a.account_id}</span><Pill tone="blue">{directionLabel(a.direction)}</Pill></span> : "Case"}
        subtitle={a && <>{a.distinct_counterparties} distinct counterparties · {a.tx_count} transactions · {fmtWindow(a.window_start, a.window_end)}</>}
        actions={<><StatusPill status={c.status} /><CheckerBadge c={c} /></>} />

      <div className="space-y-5">
        <AiBanner />
        {working && (
          <Callout tone="blue" icon="info" title={<span className="inline-flex items-center gap-2"><Spinner className="h-4 w-4" />Investigating…</span>}>
            Code is computing the fact sheet, then two helpers check regulator guidance and harmless explanations, a drafter writes
            the case file, and a code checker verifies every number and citation. This page updates automatically.
          </Callout>
        )}
        {c.status === "failed" && (
          <Callout tone="red" icon="alert" title="The investigation failed. Review the facts and decide yourself.">
            <span className="font-mono text-xs">{c.error?.code}</span> {c.error?.message}
          </Callout>
        )}
        {c.status === "needs_human_rewrite" && <NeedsRewrite errors={c.checker?.errors ?? []} />}

        {!working && (
          <div className="grid gap-5 lg:grid-cols-5">
            <div className="lg:col-span-2">
              <Card title="Fact sheet" subtitle="Computed by code from all transactions in the window. Click a fact for details." padded={false}>
                {c.facts.length ? <FactTable facts={c.facts} highlight={cited} onOpen={setEvidence} />
                  : <p className="p-5 text-sm text-slate-400">No facts were computed.</p>}
              </Card>
            </div>
            <div className="space-y-5 lg:col-span-3">
              {cf ? (
                <>
                  <Card title="AI suggestion"
                    action={<Pill tone={verdictTone[cf.verdict]} dot>{verdictLabel[cf.verdict]}</Pill>}
                    subtitle="A suggestion only. It cannot close this alert.">
                    <p className="text-sm leading-relaxed text-slate-700">{cf.summary}</p>
                  </Card>
                  <Card title="Claims" subtitle="Each claim cites the facts (F…) or guidance excerpts it relies on. Click a chip to see the evidence.">
                    <ClaimList claims={cf.claims} facts={facts} onOpen={setEvidence} />
                  </Card>
                  <div className="grid gap-5 xl:grid-cols-2">
                    <Card title="Possible harmless explanations">
                      <ClaimList claims={cf.benign_explanations} facts={facts} onOpen={setEvidence} empty="None supported by the facts." />
                    </Card>
                    <Card title="What the guidance says">
                      <ClaimList claims={cf.typology_context} facts={facts} onOpen={setEvidence} empty="No relevant guidance found." />
                    </Card>
                  </div>
                  <div className="grid gap-5 xl:grid-cols-2">
                    <Card title="Missing evidence">
                      {cf.missing_evidence.length ? (
                        <ul className="space-y-1.5 text-sm text-slate-700">
                          {cf.missing_evidence.map((m) => <li key={m} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-slate-400" />{m}</li>)}
                        </ul>
                      ) : <p className="text-sm text-slate-400">None listed.</p>}
                    </Card>
                    <Card title="Limitations"><p className="text-sm text-slate-700">{cf.limitations || "—"}</p></Card>
                  </div>
                  <p className="text-xs text-slate-400">
                    {c.model_ids.llm} · prompt {c.prompt_version} · {c.llm_calls} AI calls · {c.tokens.input.toLocaleString()} in / {c.tokens.output.toLocaleString()} out tokens
                    {c.timings.total_seconds != null && ` · ${c.timings.total_seconds} s`}
                  </p>
                </>
              ) : !working && (
                <Card title="No AI draft"><p className="text-sm text-slate-500">Use the fact sheet to decide.</p></Card>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="fixed inset-x-0 bottom-0 z-30 pl-60">
        <div className="mx-auto max-w-7xl px-8 pb-6"><DecisionBar c={c} /></div>
      </div>
      <EvidenceDrawer evidence={evidence} onClose={() => setEvidence(null)} />
    </div>
  );
}

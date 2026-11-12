import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { Case, Claim, Decision, Fact } from "../api/types";
import { useAnalyst } from "../lib/analyst";
import { decisionLabel, fmtDateTime, fmtNum, parseChunkId } from "../lib/format";
import { Button, Callout, cx, ErrorBox, Icon, Loading, Pill } from "./ui";

export type Evidence = { kind: "fact"; fact: Fact } | { kind: "chunk"; id: string };

// ---------------- banners and badges ----------------
export function AiBanner() {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-brand-100 bg-brand-50 px-4 py-2.5 text-sm text-brand-800">
      <Icon name="shield" className="h-4 w-4" />
      <span><span className="font-semibold">AI draft. A human decides.</span> Every number comes from code; every claim cites its evidence.</span>
    </div>
  );
}

export function CheckerBadge({ c }: { c: Case }) {
  if (c.status === "failed") return <Pill tone="red" dot>Run failed</Pill>;
  if (c.status === "needs_human_rewrite") return <Pill tone="amber" dot>Failed checks: write it yourself</Pill>;
  if (c.checker?.passed) return <Pill tone="green" dot>Checks passed{c.checker.attempts > 1 ? " after 1 retry" : ""}</Pill>;
  return null;
}

// ---------------- fact rendering ----------------
export function FactValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-slate-400">not available</span>;
  if (typeof value === "number") return <span className="tabular-nums">{fmtNum(value)}</span>;
  if (typeof value === "boolean") return <span>{value ? "yes" : "no"}</span>;
  if (typeof value === "string") return <span>{value}</span>;
  if (Array.isArray(value)) return (
    <div className="space-y-1">
      {value.length === 0 ? <span className="text-slate-400">none</span> : value.map((v, i) => (
        <div key={i} className="rounded bg-slate-50 px-2 py-1 text-xs"><FactValue value={v} /></div>
      ))}
    </div>
  );
  const entries = Object.entries(value as Record<string, unknown>);
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k.replace(/_/g, " ")}</dt>
          <dd className="font-medium text-slate-800">{typeof v === "object" && v !== null ? <FactValue value={v} /> : <FactValue value={v} />}</dd>
        </div>
      ))}
    </dl>
  );
}

export function FactTable({ facts, highlight, onOpen }: { facts: Fact[]; highlight: Set<string>; onOpen: (e: Evidence) => void }) {
  return (
    <div className="divide-y divide-slate-100">
      {facts.map((f) => (
        <button key={f.id} onClick={() => onOpen({ kind: "fact", fact: f })}
          className={cx("grid w-full grid-cols-[3rem_1fr] gap-3 px-5 py-3 text-left transition hover:bg-slate-50",
            highlight.has(f.id) && "bg-brand-50/50")}>
          <span className="mt-0.5 font-mono text-xs font-semibold text-brand-700">{f.id}</span>
          <span className="min-w-0">
            <span className="block text-xs font-medium text-slate-500">{f.label}{f.unit && <span className="text-slate-400"> · {f.unit}</span>}</span>
            <span className="mt-1 block text-sm text-slate-900"><FactValue value={f.value} /></span>
          </span>
        </button>
      ))}
    </div>
  );
}

// ---------------- claims and evidence chips ----------------
export function EvidenceChip({ id, facts, onOpen }: { id: string; facts: Record<string, Fact>; onOpen: (e: Evidence) => void }) {
  const isFact = id in facts || /^F\d+$/.test(id);
  const label = isFact ? id : (() => { const c = parseChunkId(id); return c.page ? `${c.doc.split(" ")[0]} p.${c.page}` : id; })();
  return (
    <button onClick={() => (isFact && facts[id] ? onOpen({ kind: "fact", fact: facts[id] }) : onOpen({ kind: "chunk", id }))}
      title={isFact ? facts[id]?.label : id}
      className={cx("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono text-[11px] font-medium transition",
        isFact ? "border-brand-100 bg-brand-50 text-brand-700 hover:border-brand-600"
               : "border-violet-200 bg-violet-50 text-violet-700 hover:border-violet-500")}>
      <Icon name={isFact ? "fact" : "doc"} className="h-3 w-3" />{label}
    </button>
  );
}

export function ClaimList({ claims, facts, onOpen, empty }: {
  claims: Claim[]; facts: Record<string, Fact>; onOpen: (e: Evidence) => void; empty?: string;
}) {
  if (!claims.length) return <p className="text-sm text-slate-400">{empty ?? "None."}</p>;
  return (
    <ul className="space-y-2.5">
      {claims.map((c, i) => (
        <li key={i} className="rounded-lg border border-slate-200 bg-white px-4 py-3">
          <p className="text-sm leading-relaxed text-slate-800">{c.text}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {[...c.fact_ids, ...c.chunk_ids].map((id) => <EvidenceChip key={id} id={id} facts={facts} onOpen={onOpen} />)}
          </div>
        </li>
      ))}
    </ul>
  );
}

// ---------------- evidence drawer ----------------
export function EvidenceDrawer({ evidence, onClose }: { evidence: Evidence | null; onClose: () => void }) {
  const chunkId = evidence?.kind === "chunk" ? evidence.id : null;
  const chunk = useQuery({ queryKey: ["chunk", chunkId], queryFn: () => api.chunk(chunkId!), enabled: !!chunkId });
  if (!evidence) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal>
      <div className="absolute inset-0 bg-slate-900/20" onClick={onClose} />
      <aside className="drawer-in relative flex h-full w-full max-w-lg flex-col bg-white shadow-2xl">
        <header className="flex items-start justify-between border-b border-slate-200 px-6 py-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              {evidence.kind === "fact" ? "Fact computed by code" : "Regulatory guidance excerpt"}
            </div>
            <h3 className="mt-1 text-base font-semibold text-slate-900">
              {evidence.kind === "fact" ? `${evidence.fact.id} · ${evidence.fact.label}` : chunk.data?.title ?? evidence.id}
            </h3>
          </div>
          <button onClick={onClose} className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Close">
            <Icon name="x" className="h-5 w-5" />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {evidence.kind === "fact" ? (
            <div className="space-y-4">
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm"><FactValue value={evidence.fact.value} /></div>
              <dl className="grid grid-cols-[6rem_1fr] gap-y-2 text-sm">
                <dt className="text-slate-500">Unit</dt><dd>{evidence.fact.unit ?? "—"}</dd>
                <dt className="text-slate-500">Source</dt><dd className="font-mono text-xs">{evidence.fact.source}</dd>
              </dl>
              <p className="text-xs text-slate-500">Computed from the transactions in the alert window. The AI only copied it.</p>
            </div>
          ) : chunk.isLoading ? <Loading /> : chunk.isError ? <ErrorBox error={chunk.error} /> : chunk.data && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <Pill tone="violet">page {chunk.data.page}</Pill>
                <span className="font-mono">{chunk.data.chunk_id}</span>
              </div>
              <blockquote className="whitespace-pre-line border-l-2 border-violet-300 pl-4 text-sm leading-relaxed text-slate-700">{chunk.data.text}</blockquote>
              <a href={chunk.data.source_url} target="_blank" rel="noreferrer"
                className="inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline">
                Open the source document <Icon name="external" className="h-3.5 w-3.5" />
              </a>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

// ---------------- decision bar ----------------
const CHOICES: { d: Decision; label: string; variant: "success" | "danger" | "warning"; hint: string }[] = [
  { d: "dismiss", label: "Dismiss", variant: "success", hint: "Close as a false alarm" },
  { d: "escalate", label: "Escalate", variant: "danger", hint: "Send for further investigation" },
  { d: "need_info", label: "Need info", variant: "warning", hint: "Ask for more evidence" },
];

export function DecisionBar({ c }: { c: Case }) {
  const [analyst, setAnalyst] = useAnalyst();
  const [reason, setReason] = useState("");
  const [choice, setChoice] = useState<Decision | null>(null);
  const qc = useQueryClient();
  const decide = useMutation({
    mutationFn: (d: Decision) => api.decide(c.case_id, { decision: d, reason: reason.trim(), analyst: analyst.trim() }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["case", c.case_id] }); qc.invalidateQueries({ queryKey: ["alerts"] });
      qc.invalidateQueries({ queryKey: ["decision-counts"] }); },
  });

  if (c.decision) {
    const ack = c.decision.mock_case_system;
    return (
      <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-5 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <Icon name="check" className="h-5 w-5 text-emerald-700" />
          <span className="text-sm font-semibold text-emerald-900">{decisionLabel[c.decision.decision]} by {c.decision.analyst}</span>
          <span className="text-xs text-emerald-800">{fmtDateTime(c.decision.decided_at)}</span>
          <span className="ml-auto text-xs">
            {ack?.ok ? <Pill tone="green">Recorded in case system · {ack.external_id}</Pill>
                     : <Pill tone="amber">Case system not reached{ack?.error ? ` (${ack.error})` : ""}</Pill>}
          </span>
        </div>
        <p className="mt-2 text-sm text-emerald-900/80">“{c.decision.reason}”</p>
      </div>
    );
  }
  const canDecide = ["checked", "needs_human_rewrite", "failed"].includes(c.status);
  const ready = canDecide && reason.trim().length >= 3 && analyst.trim().length > 0;
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-lg shadow-slate-200/60">
      <div className="flex flex-wrap items-start gap-4">
        <div className="min-w-64 flex-1">
          <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Your decision and reason (required)</label>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={1000} disabled={!canDecide}
            placeholder="Why? e.g. Regular payroll-style payments to repeat counterparties."
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-brand-600 focus:outline-none focus:ring-4 focus:ring-brand-100 disabled:bg-slate-50" />
          {!analyst.trim() && (
            <input value={analyst} onChange={(e) => setAnalyst(e.target.value)} placeholder="Your name"
              className="mt-2 w-60 rounded-lg border border-slate-300 px-3 py-1.5 text-sm shadow-sm focus:border-brand-600 focus:outline-none" />
          )}
        </div>
        <div className="flex flex-col gap-2 pt-6">
          <div className="flex gap-2">
            {CHOICES.map((o) => (
              <Button key={o.d} variant={o.variant} title={o.hint} disabled={!ready || decide.isPending}
                loading={decide.isPending && choice === o.d} onClick={() => { setChoice(o.d); decide.mutate(o.d); }}>
                {o.label}
              </Button>
            ))}
          </div>
          {!canDecide && <span className="text-xs text-slate-500">Available when the investigation has finished.</span>}
        </div>
      </div>
      {decide.isError && <div className="mt-3"><ErrorBox error={decide.error} title="Decision not saved" /></div>}
    </div>
  );
}

export function NeedsRewrite({ errors }: { errors: string[] }) {
  return (
    <Callout tone="amber" icon="alert" title="The AI draft failed checks. Write the case file yourself.">
      The draft below is kept for reference only. The facts on the left are correct (computed by code).
      <ul className="mt-2 list-disc space-y-0.5 pl-5 font-mono text-xs">{errors.slice(0, 8).map((e) => <li key={e}>{e}</li>)}</ul>
    </Callout>
  );
}

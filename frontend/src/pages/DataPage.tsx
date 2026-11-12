import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Upload } from "../api/types";
import { Button, Callout, Card, cx, EmptyState, ErrorBox, Icon, Loading, PageHeader, Pill, StatusPill } from "../components/ui";
import { fmtDateTime } from "../lib/format";

const fmtBytes = (b: number) => (b > 1 << 20 ? `${(b / (1 << 20)).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
const reasonLabel: Record<string, string> = {
  bad_timestamp: "Unreadable timestamp", bad_amount: "Missing or non-positive amount",
  missing_field: "Missing required field", before_data_origin: "Earlier than the loaded data",
};

export default function DataPage() {
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const uploads = useQuery({
    queryKey: ["uploads"], queryFn: api.uploads,
    refetchInterval: (q) => (q.state.data?.items.some((u) => ["validating", "appending"].includes(u.status)) ? 1500 : false),
  });
  const m = meta.data;
  return (
    <>
      <PageHeader title="Data"
        subtitle="Add new transactions as files in the IBM transaction format. New rows are appended to what is already loaded; rows that are already loaded are skipped." />
      <div className="grid gap-6 lg:grid-cols-5">
        <div className="lg:col-span-3"><UploadForm disabled={!m?.data_loaded} /></div>
        <div className="lg:col-span-2">
          <Card title="Loaded data">
            {meta.isLoading ? <Loading /> : !m?.data_loaded ? (
              <Callout tone="amber" icon="info" title="No base data yet">Run the pipeline once (python -m pipeline.run --step all) before uploading.</Callout>
            ) : (
              <dl className="grid grid-cols-[8rem_1fr] gap-y-2.5 text-sm">
                <dt className="text-slate-500">Dataset</dt><dd className="font-medium">IBM AML {m.dataset} (simulated)</dd>
                <dt className="text-slate-500">From</dt><dd>{fmtDateTime(m.data_origin)}</dd>
                <dt className="text-slate-500">Up to</dt><dd>{fmtDateTime(m.slice_end)}</dd>
                <dt className="text-slate-500">Length</dt><dd className="font-medium tabular-nums">{m.slice_hours} hours</dd>
                <dt className="text-slate-500">Payment formats</dt><dd className="text-slate-700">{m.payment_formats.join(", ")}</dd>
              </dl>
            )}
          </Card>
        </div>
      </div>
      <div className="mt-6">
        <Card title="Uploads" subtitle="Newest first" padded={false}>
          {uploads.isLoading ? <Loading /> : uploads.isError ? <div className="p-5"><ErrorBox error={uploads.error} /></div>
            : !uploads.data?.items.length ? <EmptyState icon="upload" title="No uploads yet">Upload the next day of transactions to see new alerts appear.</EmptyState>
            : <div className="divide-y divide-slate-100">{uploads.data.items.map((u) => <UploadRow key={u.upload_id} u={u} />)}</div>}
        </Card>
      </div>
    </>
  );
}

function UploadForm({ disabled }: { disabled: boolean }) {
  const [file, setFile] = useState<File | null>(null);
  const [patterns, setPatterns] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const create = useMutation({
    mutationFn: () => api.createUpload(file!, patterns),
    onSuccess: () => { setFile(null); setPatterns(null); qc.invalidateQueries({ queryKey: ["uploads"] }); },
  });
  return (
    <Card title="Upload transactions" subtitle="CSV with the 11 IBM columns (Timestamp, From Bank, Account, To Bank, Account, amounts, currencies, Payment Format, Is Laundering).">
      <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) setFile(f); }}
        onClick={() => !disabled && input.current?.click()}
        className={cx("flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition",
          drag ? "border-brand-600 bg-brand-50" : "border-slate-300 bg-slate-50/50 hover:border-slate-400",
          disabled && "cursor-not-allowed opacity-50")}>
        <div className="mb-3 rounded-full bg-white p-3 text-brand-700 shadow-sm ring-1 ring-slate-200"><Icon name="upload" className="h-6 w-6" /></div>
        {file ? (
          <p className="text-sm font-medium text-slate-900">{file.name} <span className="font-normal text-slate-500">· {fmtBytes(file.size)}</span></p>
        ) : (
          <><p className="text-sm font-medium text-slate-900">Drop a CSV here or click to choose</p>
            <p className="mt-1 text-xs text-slate-500">Up to 300 MB. Nothing is saved until you confirm.</p></>
        )}
        <input ref={input} type="file" accept=".csv" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </div>
      <label className="mt-4 flex items-center gap-3 text-sm text-slate-600">
        <span className="whitespace-nowrap">Patterns file (optional)</span>
        <input type="file" accept=".txt" onChange={(e) => setPatterns(e.target.files?.[0] ?? null)} disabled={disabled}
          className="text-xs file:mr-3 file:rounded-md file:border file:border-slate-300 file:bg-white file:px-2.5 file:py-1 file:text-xs file:font-medium file:text-slate-700" />
      </label>
      <p className="mt-1 text-xs text-slate-500">With IBM's patterns file, pattern recall can be measured on the new data too.</p>
      {create.isError && <div className="mt-3"><ErrorBox error={create.error} title="Upload failed" /></div>}
      <div className="mt-4 flex justify-end border-t border-slate-100 pt-4">
        <Button disabled={!file || disabled} loading={create.isPending} onClick={() => create.mutate()}>
          <Icon name="upload" />Upload and check
        </Button>
      </div>
    </Card>
  );
}

function UploadRow({ u }: { u: Upload }) {
  const qc = useQueryClient();
  const append = useMutation({ mutationFn: () => api.appendUpload(u.upload_id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["uploads"] }); qc.invalidateQueries({ queryKey: ["meta"] }); } });
  const runNew = useMutation({ mutationFn: api.runAllOnNewData,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scenarios"] }) });
  const r = u.report;
  return (
    <div className="px-5 py-4">
      <div className="flex flex-wrap items-center gap-3">
        <Icon name="database" className="h-4 w-4 text-slate-400" />
        <span className="font-medium text-slate-900">{u.filename}</span>
        <span className="text-xs text-slate-500">{fmtBytes(u.bytes)} · {fmtDateTime(u.created_at)}{u.has_patterns && " · with patterns file"}</span>
        <span className="ml-auto"><StatusPill status={u.status} /></span>
      </div>

      {u.status === "validating" && <p className="mt-2 text-sm text-slate-500">Checking every row…</p>}
      {u.status === "invalid" && <div className="mt-3"><Callout tone="red" icon="alert" title="Not added">{r?.error}</Callout></div>}
      {u.status === "failed" && <div className="mt-3"><Callout tone="red" icon="alert" title="Append failed">{u.error}</Callout></div>}

      {r?.ok && u.status !== "appended" && (
        <div className="mt-3 grid gap-3 sm:grid-cols-4">
          {[["Rows read", r.rows], ["Will be added", r.to_append], ["Already loaded", r.already_loaded], ["Rejected", r.rejected]].map(([l, v]) => (
            <div key={l as string} className="rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-2">
              <div className="text-xs text-slate-500">{l}</div>
              <div className="text-lg font-semibold tabular-nums text-slate-900">{(v as number)?.toLocaleString("en-US")}</div>
            </div>
          ))}
        </div>
      )}
      {r?.ok && u.status !== "appended" && (
        <div className="mt-3 space-y-2 text-sm text-slate-600">
          <p>Transactions from <span className="font-medium">{fmtDateTime(r.ts_min)}</span> to <span className="font-medium">{fmtDateTime(r.ts_max)}</span>
            {r.labeled_rows ? <> · {r.labeled_rows} rows carry a laundering label (kept hidden from the AI)</> : null}.</p>
          {r.reasons && Object.keys(r.reasons).length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(r.reasons).map(([k, n]) => <Pill key={k} tone="amber">{reasonLabel[k] ?? k}: {n}</Pill>)}
              {r.examples?.length ? <span className="text-xs text-slate-500">e.g. row {r.examples.slice(0, 5).map((e) => e.row).join(", ")}</span> : null}
            </div>
          )}
        </div>
      )}
      {u.status === "validated" && (
        <div className="mt-4 flex items-center gap-3">
          <Button onClick={() => append.mutate()} loading={append.isPending}><Icon name="check" />Add {r?.to_append?.toLocaleString("en-US")} rows to the data</Button>
          {append.isError && <ErrorBox error={append.error} />}
        </div>
      )}
      {u.status === "appending" && <p className="mt-2 text-sm text-slate-500">Adding rows…</p>}

      {u.status === "appended" && u.result && (
        <div className="mt-3 space-y-3">
          <Callout tone="green" icon="check" title={`${u.result.appended.toLocaleString("en-US")} rows added`}>
            {u.result.already_loaded > 0 && `${u.result.already_loaded} already loaded were skipped. `}
            Data now runs to {fmtDateTime(u.result.data_end)}. {u.s3_key ? "The original file is kept in S3." : "S3 copy pending (no bucket configured)."}
          </Callout>
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => runNew.mutate()} loading={runNew.isPending}><Icon name="play" />Run approved scenarios on new data</Button>
            {runNew.data && (
              <span className="text-sm text-slate-600">
                Started {runNew.data.started.length} run(s){runNew.data.skipped.length ? `, ${runNew.data.skipped.length} skipped (no complete new window yet)` : ""}.{" "}
                <Link to="/alerts?status=new" className="font-medium text-brand-700 hover:underline">See new alerts →</Link>
              </span>
            )}
            {runNew.isError && <ErrorBox error={runNew.error} />}
          </div>
        </div>
      )}
    </div>
  );
}

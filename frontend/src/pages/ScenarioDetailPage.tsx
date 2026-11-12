import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { RunHistory, RunPanel } from "../components/runs";
import { ExamplesTable, MetricsCards, RunStatus, SpecEditor } from "../components/scenario";
import { ErrorBox, Icon, Loading, PageHeader, StatusPill } from "../components/ui";
import { fmtDateTime } from "../lib/format";

export default function ScenarioDetailPage() {
  const { id = "" } = useParams();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: 60_000 });
  const q = useQuery({
    queryKey: ["scenario", id], queryFn: () => api.scenario(id),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2000 : false),   // poll while running
  });
  if (q.isLoading) return <Loading />;
  if (q.isError || !q.data) return <ErrorBox error={q.error} title="Could not load the scenario" />;
  const s = q.data;
  const run = s.latest_run;
  return (
    <>
      <Link to="/scenarios" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <Icon name="arrow-left" />Scenario Studio
      </Link>
      <PageHeader eyebrow={<>Scenario · created {fmtDateTime(s.created_at)}{s.cloned_from && " · clone"}</>}
        title={<span className="flex items-center gap-3">“{s.intent_text}”</span>}
        actions={<StatusPill status={s.status} />} />
      <div className="space-y-6">
        <SpecEditor scenario={s} meta={meta.data} />
        <RunPanel scenario={s} meta={meta.data} />
        <RunStatus run={run} />
        {run?.status === "completed" && run.metrics && (
          <>
            {run.mode && run.mode !== "all" && run.range_start && (
              <p className="text-sm text-slate-600">
                Latest run: <span className="font-medium">{run.mode === "new" ? "new data" : "date range"}</span> {fmtDateTime(run.range_start)} → {fmtDateTime(run.range_end)}
              </p>
            )}
            <MetricsCards run={run} scenarioId={s.scenario_id} />
            <RunHistory scenarioId={s.scenario_id} refreshKey={run.run_id} />
            <ExamplesTable scenarioId={s.scenario_id} />
          </>
        )}
      </div>
    </>
  );
}

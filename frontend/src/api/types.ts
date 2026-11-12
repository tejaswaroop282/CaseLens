// Mirrors the backend Pydantic models and API responses (docs/04 section 4.3).

export type Direction = "out" | "in";
export interface ScenarioParams { min_counterparties: number; window_hours: number; payment_formats: string[] | null }
export interface ScenarioSpec {
  direction: Direction | null; params: ScenarioParams | null; legitimate_lookalikes: string[];
  rationale: string; unsupported_reason: string | null;
}
export type ScenarioStatus = "draft" | "approved" | "running" | "completed" | "failed" | "rejected";
export interface Problem { code: string; message: string; details: Record<string, unknown> }
export interface RunMetrics {
  alert_count: number; suspicious_alert_count: number; alert_precision: number | null; false_alarm_count: number;
  pattern_type: string; pattern_recall: { caught: number; total: number; recall: number | null };
  duration_seconds: number; slice_hours: number;
}
export interface RuleRun {
  run_id: string; status: "running" | "completed" | "failed"; error: { code: string; message: string } | null;
  metrics: RunMetrics | null; started_at: string; finished_at: string | null;
}
export interface Scenario {
  scenario_id: string; intent_text: string; spec: ScenarioSpec; status: ScenarioStatus;
  validation_problems?: Problem[]; created_at: string; approved_at: string | null; approved_by: string | null;
  cloned_from?: string; latest_run?: RuleRun | null;
}
export interface Page<T> { items: T[]; page: number; page_size: number; total: number }

export interface AlertSummary {
  alert_id: string; account_id: string; direction: Direction; window_start: string; window_end: string;
  distinct_counterparties: number; tx_count: number; first_ts: string; last_ts: string;
}
export interface ExampleItem extends AlertSummary { is_suspicious: boolean; n_laundering_tx: number; pattern_types: string[] }
export interface Examples { hits: ExampleItem[]; look_alikes: ExampleItem[] }

export type Verdict = "likely_legitimate" | "needs_review" | "likely_suspicious";
export type CaseStatus = "queued" | "running" | "checked" | "needs_human_rewrite" | "failed" | "decided";
export interface CaseSummary { case_id: string; status: CaseStatus; verdict: Verdict | null }
export interface Alert extends AlertSummary {
  scenario_id: string; run_id: string; bucket: number; window_hours: number;
  status: "new" | "investigating" | "reviewed"; created_at: string; latest_case: CaseSummary | null;
}
export interface Fact { id: string; label: string; value: unknown; unit: string | null; source: string }
export interface Claim { text: string; fact_ids: string[]; chunk_ids: string[] }
export interface CaseFile {
  verdict: Verdict; summary: string; claims: Claim[]; benign_explanations: Claim[]; typology_context: Claim[];
  missing_evidence: string[]; limitations: string;
}
export type Decision = "dismiss" | "escalate" | "need_info";
export interface DecisionDoc {
  decision_id: string; case_id: string; alert_id: string; decision: Decision; reason: string; analyst: string;
  decided_at: string; ai_verdict: Verdict | null;
  mock_case_system?: { ok: boolean; status_code?: number; external_id?: string; error?: string };
}
export interface Case {
  case_id: string; alert_id: string; scenario_id: string; status: CaseStatus; facts: Fact[];
  typology_notes: Claim[]; benign_notes: Claim[]; missing_evidence: string[]; retrieved_chunk_ids: string[];
  case_file: CaseFile | null; checker: { passed: boolean; errors: string[]; attempts: number } | null;
  model_ids: { llm: string | null }; prompt_version: string; llm_calls: number;
  tokens: { input: number; output: number }; timings: { total_seconds?: number };
  error: { code: string; message: string } | null; created_at: string; finished_at: string | null;
  decision: DecisionDoc | null; alert: Alert | null;
}
export interface Chunk { chunk_id: string; title: string; page: number; source_url: string; text: string }
export interface Meta {
  data_loaded: boolean; slice_hours: number | null; data_origin: string | null; slice_end: string | null;
  dataset: string | null; payment_formats: string[]; model_id: string | null; prompt_version: string;
}
export interface DecisionCounts { dismiss: number; escalate: number; need_info: number }

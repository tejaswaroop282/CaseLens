import type {
  Alert, Case, Chunk, DecisionCounts, DecisionDoc, Decision, Examples, Meta, Page, Scenario, ScenarioParams,
} from "./types";

const BASE: string = import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, unknown> = {}) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the CaseLens API. Is the backend running on port 8000?");
  }
  if (!res.ok) {
    let body: { error?: { code: string; message: string; details?: Record<string, unknown> } } = {};
    try { body = await res.json(); } catch { /* not JSON */ }
    throw new ApiError(res.status, body.error?.code ?? "error", body.error?.message ?? res.statusText, body.error?.details);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });

export const api = {
  meta: () => request<Meta>("/meta"),
  scenarios: (page = 1) => request<Page<Scenario>>(`/scenarios?page=${page}&page_size=50`),
  scenario: (id: string) => request<Scenario>(`/scenarios/${id}`),
  parse: (intent_text: string) => post<Scenario>("/scenarios/parse", { intent_text }),
  patch: (id: string, body: { direction?: "out" | "in"; params?: Partial<ScenarioParams> }) =>
    request<Scenario>(`/scenarios/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  approve: (id: string, approved_by: string) => post<{ status: string }>(`/scenarios/${id}/approve`, { approved_by }),
  run: (id: string) => post<{ run_id: string; status: string }>(`/scenarios/${id}/run`),
  clone: (id: string) => post<Scenario>(`/scenarios/${id}/clone`),
  examples: (id: string, k = 5) => request<Examples>(`/scenarios/${id}/examples?k=${k}`),
  alerts: (q: { scenario_id?: string; status?: string; page: number }) => {
    const p = new URLSearchParams({ page: String(q.page), page_size: "25" });
    if (q.scenario_id) p.set("scenario_id", q.scenario_id);
    if (q.status) p.set("status", q.status);
    return request<Page<Alert>>(`/alerts?${p}`);
  },
  alert: (id: string) => request<Alert>(`/alerts/${id}`),
  investigate: (alertId: string) => post<{ case_id: string; status: string }>(`/alerts/${alertId}/investigate`),
  case: (id: string) => request<Case>(`/cases/${id}`),
  chunk: (id: string) => request<Chunk>(`/chunks/${encodeURIComponent(id)}`),
  decide: (caseId: string, body: { decision: Decision; reason: string; analyst: string }) =>
    post<DecisionDoc>(`/cases/${caseId}/decision`, body),
  decisionCounts: (scenario_id?: string) =>
    request<DecisionCounts>(`/decisions/summary${scenario_id ? `?scenario_id=${scenario_id}` : ""}`),
};

# 04 — API and frontend (M3, M5)

The FastAPI backend and the React dev server run directly on Windows. Backend: `uvicorn app.main:app --reload --port 8000` from `backend/`. Frontend: `npm run dev` (port 5173).

## 1. API conventions

- Base path `/api`. JSON only. `snake_case` keys. Times are ISO 8601 UTC strings.
- Sync endpoints (`def`, not `async def`) using `pymongo`. Long work uses `BackgroundTasks`.
- Error body: `{"error": {"code": "string", "message": "string", "details": {}}}`.

| HTTP | `code` examples |
|---|---|
| 400 | `bad_request` |
| 404 | `not_found` |
| 409 | `invalid_state` (for example running an unapproved scenario) |
| 422 | `validation_error`, `unknown_payment_format`, `intent_too_long` |
| 402 | `llm_budget_exhausted` (token budget used up) |
| 502 | `llm_unavailable`, `parse_failed` |
| 500 | `internal_error` |

- Paging: `?page=1&page_size=50` (max 200). Response: `{"items": [...], "page": 1, "page_size": 50, "total": 1832}`.
- CORS: allow `http://localhost:5173`.
- Request id middleware: header `X-Request-ID` in, echoed out, added to every log line.
- **Truth rule:** only `GET /scenarios/{id}/examples` may include ground-truth fields. All other endpoints must never return them. Evaluation numbers come from `eval/` scripts, not from the API.

## 2. Endpoints

### Health
`GET /health` → `{"status": "ok", "mongo": true, "chroma": true, "tokens_remaining": {"input": 0, "output": 0}}` (also checks that `pipeline_meta` exists: `"data_loaded": true`).

### Scenarios

`POST /scenarios/parse`
```json
{"intent_text": "Flag accounts that receive money from at least 20 different accounts within 12 hours."}
```
→ 201
```json
{"scenario_id": "…", "status": "draft", "intent_text": "…",
 "spec": {"direction": "in", "params": {"min_counterparties": 20, "window_hours": 12, "payment_formats": null},
          "legitimate_lookalikes": ["payroll collections"], "rationale": "…", "unsupported_reason": null}}
```
A worry that is not the fan pattern: still 201 with `spec.direction = null` and `unsupported_reason` set; status `draft` (the UI shows the reason and blocks approval).

`GET /scenarios` → list. `GET /scenarios/{id}` → one.

`PATCH /scenarios/{id}` (only in `draft`; direction and params only; revalidated, including `window_hours` at most `SLICE_HOURS`)
```json
{"params": {"min_counterparties": 15, "window_hours": 24}}
```

`POST /scenarios/{id}/approve` → `{"status": "approved", "approved_at": "…"}`. 409 if the spec has `direction = null` or the status is not `draft`. Body: `{"approved_by": "analyst name"}`.

`POST /scenarios/{id}/clone` → new `draft` with the same spec.

`POST /scenarios/{id}/run` → 202 `{"run_id": "…", "status": "running"}`. 409 unless `approved`.

`GET /scenarios/{id}` includes `latest_run: {run_id, status, error, metrics}` when a run exists.

`GET /scenarios/{id}/examples?k=5` → `{"hits": [AlertSummaryWithTruth], "look_alikes": [AlertSummaryWithTruth]}`; each item has `is_suspicious` and `pattern_types`.

### Alerts

`GET /alerts?scenario_id=&status=&page=&page_size=` and `GET /alerts/{alert_id}` (alert fields plus `latest_case: {case_id, status, verdict}` or null). **No truth fields.**

`POST /alerts/{alert_id}/investigate` → 202 `{"case_id": "…", "status": "queued"}`. 409 if a case for this alert is already `queued` or `running`.

### Cases

`GET /cases/{case_id}` → the case document from `docs/03` (facts, claims, checker result, status). No truth fields.

`GET /chunks/{chunk_id}` → `{"chunk_id", "title", "page", "source_url", "text"}` (read from Chroma by id). Used by evidence chips.

`POST /cases/{case_id}/decision`
```json
{"decision": "dismiss", "reason": "Regular payroll-style payments to repeat counterparties.", "analyst": "Ravi"}
```
`decision` is `dismiss`, `escalate` or `need_info`. `reason` is required (3 to 1000 characters). Allowed when the case status is `checked`, `needs_human_rewrite` or `failed`. Effects (in order): insert into `decisions` (append only), set case `decided`, set alert `reviewed`, forward to the mock case system. Return 201 with the decision document.

### Mock case system (simulates the downstream system)

`POST /mock-case-system/cases` body `{"case_id","alert_id","decision","reason","analyst","decided_at"}` → 201 and stored in `mock_case_system`. `GET /mock-case-system/cases` → list. The backend calls its own route (HTTP) after each decision, with a 3 s timeout; failure is logged and does not fail the decision.

## 3. Background job behavior

- Each job updates its own document: scenario run → `rule_runs`; investigation → `cases`. Run one job at a time per process (keep it simple).
- On startup, any `running` rule run or case left from a crash is set to `failed` with error `interrupted` (simple recovery).
- The UI polls: `GET /scenarios/{id}` every 2 s while `running`; `GET /cases/{id}` every 2 s while `queued` or `running`.

## 4. Frontend (React + Vite + TypeScript)

Libraries: `react-router-dom`, `@tanstack/react-query`. Styling: plain CSS or Tailwind (pick one). Optional `recharts`. No auth. The analyst name is a text box stored in `localStorage` (this is a UI preference, not data).

### 4.1 Routes

| Route | Page |
|---|---|
| `/` | redirect to `/scenarios` |
| `/scenarios` | Scenario Studio (list + create) |
| `/scenarios/:id` | Scenario detail: spec editor, run, results, examples |
| `/alerts` | Alert queue (filter by scenario, status) |
| `/cases/:caseId` | Case review |

### 4.2 Components

| Component | Purpose |
|---|---|
| `IntentForm` | textarea (max 1000 chars), submit, loading and error states |
| `SpecEditor` | shows direction (out or in), editable numbers, lookalikes, rationale; blocks approve when `direction` is null (shows `unsupported_reason`); buttons Save, Approve, Run, Clone |
| `RunStatus` | shows running, failed (with error), completed |
| `MetricsCards` | alert count, precision, false alarm count, pattern recall by type |
| `ExamplesTable` | tabs "Hits" and "Look-alikes" with a plain-words note: "Real examples from the public dataset. The dataset is simulated." |
| `AlertTable` | paged table: account, window, counterparties, transactions, case status; row click opens the alert; "Investigate" button |
| `CaseView` | layout for the case review page |
| `FactTable` | all facts with id, label, value |
| `ClaimList` | each claim with `EvidenceChip`s |
| `EvidenceChip` | chip labeled `F2` or `c_…`; click opens `EvidenceDrawer` |
| `EvidenceDrawer` | for a fact: label, value, source. For a chunk: text, title, page, link (calls `GET /chunks/{id}`) |
| `CheckerBadge` | green "Checks passed", amber "Failed checks: write it yourself", red "Run failed" |
| `DecisionBar` | three buttons (Dismiss, Escalate, Need info), required reason box, analyst name; disabled after decision |
| `AiBanner` | always visible on the case page: "AI draft. A human decides." |

### 4.3 Types (mirror the Pydantic models; keep in `src/api/types.ts`)

```ts
export type Direction = "out" | "in";
export interface ScenarioParams { min_counterparties: number; window_hours: number; payment_formats: string[] | null }
export interface ScenarioSpec { direction: Direction | null; params: ScenarioParams | null; legitimate_lookalikes: string[]; rationale: string; unsupported_reason: string | null }
export type Verdict = "likely_legitimate" | "needs_review" | "likely_suspicious";
export interface Fact { id: string; label: string; value: unknown; unit: string | null; source: string }
export interface Claim { text: string; fact_ids: string[]; chunk_ids: string[] }
export interface CaseFile { verdict: Verdict; summary: string; claims: Claim[]; benign_explanations: Claim[]; typology_context: Claim[]; missing_evidence: string[]; limitations: string }
export type CaseStatus = "queued" | "running" | "checked" | "needs_human_rewrite" | "failed" | "decided";
export type Decision = "dismiss" | "escalate" | "need_info";
```

### 4.4 Behavior rules

- Every list and page has loading, error and empty states.
- Case review shows **no ground truth**. The verdict is shown as "AI suggestion".
- Evidence chips are the main trust feature: clicking a claim's chip must show the exact fact or document text it relies on.
- Approve, Run and Decision buttons are disabled while a request is in flight.
- After a decision, show the stored decision and the mock-system acknowledgement. The Alert queue header shows counts of decided cases by decision.
- No secret keys in the frontend. `VITE_API_BASE` is the only config.

### 4.5 Frontend tests (optional, Vitest)
`EvidenceChip opens the drawer`, `SpecEditor blocks approve when direction is null`, `DecisionBar requires a reason`.

## 5. Backend API tests

- `test_parse_endpoint_with_fake_llm_returns_draft`; `test_parse_rejects_empty_and_long_intent`
- `test_patch_only_in_draft`; `test_approve_requires_supported_direction`; `test_run_requires_approved`
- `test_alerts_endpoint_has_no_truth_fields`; `test_case_endpoint_has_no_truth_fields`
- `test_examples_endpoint_includes_truth`
- `test_parse_returns_402_when_token_budget_exhausted`
- `test_patch_rejects_window_longer_than_slice`
- `test_investigate_conflict_when_running`
- `test_decision_requires_reason_and_valid_state`; `test_decision_is_append_only_and_updates_statuses`
- `test_decision_forwarded_to_mock_system_and_failure_does_not_block`
- `test_error_format_matches_contract`

# 03 — Investigation agents (M4)

Scope: alerts produced by the single fan rule (direction `out` or `in`). One small Bedrock model; every call goes through the token budget guard (`reference/budget.py`).

Flow: **build facts (code) → typology agent (LLM + Chroma) ∥ benign agent (LLM) → drafter (LLM) → evidence checker (code) → [one retry] → human.**

Reference code: `reference/models.py` (`Fact`, `Claim`, `CaseFile`), `reference/checker.py`, `reference/graph.py`, `reference/budget.py`. Copy, then extend. The reference tests must keep passing.

## 1. Rules that never change

1. Numbers come from code (facts). The LLM only references fact ids and copies numbers.
2. The LLM never sees labels or any truth field.
3. Every claim cites at least one fact id or chunk id. The checker enforces it.
4. Temperature 0. `max_tokens` capped. At most `MAX_LLM_CALLS_PER_CASE` LLM calls per investigation (default 6: typology 1, benign 1, drafter up to 2, plus structured-output retries). Every call carries the `BudgetCallback`; when the global token budget is used up the case ends `failed` with error `llm_budget_exhausted`.
5. A human decides. The graph never closes an alert.

## 2. Tool layer (`app/tools/`)

Read-only data-access functions used by the facts builder and the nodes. Plain Python.

Allow-list: tools may read only `alerts`, `scenarios`, `stg_transactions`, and the Chroma collection `reg_docs`. Implement `tool_collection(name)` that raises `PermissionError` for any other name. **The evaluation-only collections (`stg_labels`, `stg_pattern_blocks`, `alert_truth`) are not on the list.**

| Function | Returns | Caps |
|---|---|---|
| `get_alert(alert_id) -> AlertView` | alert fields without truth | |
| `get_window_stats(alert_id) -> WindowStats` | aggregates over the alert window (counts, amounts per currency, formats, banks, time span, amount spread) | no raw rows |
| `get_prior_activity(account_id, direction, before_ts) -> PriorActivity` | earlier same-direction activity (counts, distinct counterparties, days) | no raw rows |
| `get_counterparties(alert_id, top_n=5) -> list[CounterpartyView]` | top counterparties | `top_n` at most 10 |
| `search_reg_docs(query, k) -> list[ChunkView]` | `chunk_id, title, page, text` | `k` at most 8; text trimmed to 1,200 characters |

For direction `out`, the counterparty is the receiver and amounts are the paid amounts. For `in`, the counterparty is the sender and amounts are the received amounts.

The LLM nodes never call tools themselves. Code calls tools and gives the results to the prompt (a fixed graph, not a free-roaming agent).

## 3. Fact sheet (`investigation/facts.py`)

`build_fact_sheet(alert_id) -> list[Fact]`. Facts use **all** transactions in the alert window (full queries, not the capped tool list). Load the alert and its scenario. Let `key` = `from_account` for `out`, `to_account` for `in`. Window rows = transactions with `key == account_id`, `window_start <= ts < window_end`, plus the scenario's `payment_formats` filter (so facts match the alert).

Rounding: amounts 2 decimals, ratios 4 decimals, hours 2 decimals. All times UTC.

| Id | Label | Value |
|---|---|---|
| F0 | rule context | `{"direction", "min_counterparties", "window_hours", "window_start", "window_end", "payment_formats"}` |
| F1 | transaction count in window | integer |
| F2 | distinct counterparties in window | integer |
| F3 | total amount per currency | `{currency: total}` |
| F4 | time span in hours | `(last_ts - first_ts)` in hours; 0 if one transaction |
| F5 | payment format counts | `{format: count}` |
| F6 | prior activity | `{"history_available": bool, "prior_tx_count", "prior_distinct_counterparties", "prior_days_observed"}` from same-direction transactions with `data_origin <= ts < window_start`. `history_available` is false when `window_start == data_origin` (then counts are 0) |
| F7 | repeat counterparty share | `|window_counterparties ∩ prior_counterparties| / |window_counterparties|`; `null` if history is not available or `prior_tx_count == 0` |
| F8 | counterparty bank diversity | `{"distinct_banks": n, "top_bank_share": x}` |
| F9 | amount regularity | for the currency with the most transactions: `{"currency", "n", "mean", "std", "cv"}`; `std` is population standard deviation; `cv = std / mean`; `null` when `n < 2` or `mean == 0` |
| F10 | top counterparties | up to 5 `{"account_id", "tx_count", "total_amount"}` sorted by `tx_count` desc then `total_amount` desc |

Example:

```json
{"id": "F2", "label": "distinct counterparties in window", "value": 12, "unit": "accounts", "source": "facts.window_stats"}
```

The checker has an optional `hard_red_flag` argument. It is **unused in the prototype** (always false); keep the argument for later extensions.

Tests: `test_facts_match_pandas_oracle_on_fixture` (fixture with known answers for every fact), `test_f6_unavailable_in_first_window`, `test_f9_null_for_single_tx`, `test_facts_respect_payment_format_filter`.

## 4. Typed outputs for the helper agents

Add to `models/case.py`:

```python
class TypologyNotes(BaseModel):
    items: list[Claim] = Field(default_factory=list, max_length=3)      # each must have chunk_ids

class BenignNotes(BaseModel):
    explanations: list[Claim] = Field(default_factory=list, max_length=4)  # each must have fact_ids
    missing_evidence: list[str] = Field(default_factory=list, max_length=6)
```

## 5. Nodes (`investigation/nodes.py`)

Each node is a function `(state) -> partial state dict`. LLM nodes build `prompt | model.with_structured_output(Schema)` and call it with a run config: tags `["investigation", node_name]`, metadata `alert_id`, `scenario_id`, `prompt_version`, and `callbacks=[BudgetCallback(ledger, {"node": ..., "alert_id": ...})]`.

A per-case call counter object is passed through `config["configurable"]["calls"]`, **not** a state key (parallel nodes writing the same key would conflict). `calls.use()` raises `CallLimitExceeded` when `MAX_LLM_CALLS_PER_CASE` is reached. The global `TokenLedger` raises `TokenBudgetExceeded` when the token budget is used up.

| Node | Writes state keys | Model |
|---|---|---|
| `build_facts` | `facts`, `scenario`, `status="running"` | none |
| `typology_agent` | `typology_notes`, `retrieved_chunk_ids` | the configured model |
| `benign_agent` | `benign_notes`, `missing_evidence` | the configured model |
| `drafter` | `draft`, `draft_count` (+1), `retries` (previous `draft_count`) | the configured model |
| `evidence_checker` | `checker_errors` (empty list when passed) | none |
| `finalize_ok` / `finalize_fail` | `status` | none |

Facts are rendered for prompts as compact JSON: `[{"id": "F1", "label": "...", "value": ..., "unit": ...}]`. Never pass raw transaction rows to an LLM; only facts and chunk text.

### 5.1 typology_agent

Query text (constant per direction, in `prompts.py`):
- `out`: "indicators of money laundering where one account sends funds to many different accounts in a short period (dispersal, fan-out)"
- `in`: "indicators of money laundering where one account receives funds from many different accounts in a short period (collection, fan-in, mule accounts)"

Retrieve `TYPOLOGY_TOP_K` chunks (default 4). Prompt:

```
You help a compliance analyst. You are given excerpts from public regulator guidance and a short
description of the alert's pattern.
Task: write up to 3 short statements (maximum 2 sentences each) about what the excerpts say
regarding this kind of pattern, such as typical indicators, or why it can be suspicious or harmless.
Rules:
- Use only the excerpts. Do not use outside knowledge.
- Every statement must list the chunk_ids it comes from, copied exactly.
- Do not include numbers, account ids or amounts.
- If the excerpts say nothing relevant, return an empty list.
```

Human message: the pattern description (from F0: direction, in plain words) and the excerpts as `[chunk_id] (title, page N): text`.

### 5.2 benign_agent

```
You help a compliance analyst consider harmless explanations for an alert.
You are given a fact sheet computed by code. Each fact has an id.
Task: list up to 4 harmless explanations that are SUPPORTED by the facts (for example regular equal
amounts, mostly repeat counterparties, steady earlier activity). Also list up to 6 items of missing
evidence that would help (for example the customer's occupation or expected activity).
Rules:
- Each explanation must cite the fact_ids that support it. Write numbers as digits and copy them
  exactly from the facts.
- Do not invent customer details. You only know the facts.
- If no fact supports a harmless explanation, return an empty explanations list.
- Describe possible explanations only. Do not say the activity is legitimate or suspicious.
```

### 5.3 drafter

```
You write a draft case file for a compliance analyst. A human will review it and decide.
Inputs: a fact sheet (ids F0 to F10) computed by code, typology notes with chunk ids, and harmless
explanations with fact ids.
Rules:
1. Every claim must include fact_ids and/or chunk_ids. Use only ids that appear in the inputs.
2. Write numbers as digits and copy them exactly from the cited facts. Do not calculate new numbers.
3. Do not mention account ids or names unless they appear in the cited facts.
4. At most 6 claims, one sentence each.
5. verdict:
   - likely_legitimate only if at least one harmless explanation is supported and nothing in the
     facts points the other way.
   - likely_suspicious only if several facts point to the pattern (for example many distinct
     counterparties, no repeat counterparties, irregular amounts) and no harmless explanation is supported.
   - needs_review in every other case. When unsure, choose needs_review.
6. benign_explanations and typology_context: copy the supported items from the inputs. Do not add new ones.
7. missing_evidence: copy from the inputs and add anything else an analyst would need.
8. limitations: one or two sentences. Mention if history is not available (F6) and that the data is simulated.
```

Retry (second call only): append a human message: `Your previous draft failed these checks: {errors}. Produce a corrected draft. Fix only these issues.`

All prompts live in `prompts.py` with `PROMPT_VERSION`. Changing any prompt text means bumping the version.

## 6. Evidence checker

Use `reference/checker.py` as is. Rules (all tested):
1. Every claim, benign explanation and typology statement cites at least one fact id or chunk id.
2. Every cited id exists (facts of this case; `retrieved_chunk_ids`).
3. Every number in a claim that cites facts appears in those facts (comma formatting, rounding to the decimals written, and percent versus ratio are handled).
4. No account-id-shaped token appears unless it is in the cited facts. The pattern is `ID_PATTERN` from config; **adjust it after inspecting real ids** (the reference uses `\b[0-9A-F]{8,12}\b`).
5. Typology statements need chunk ids and must contain no numbers.
6. `likely_legitimate` needs at least one benign explanation (the hard-red-flag option is unused).

Known limits (state in the README): numbers written as words are not checked, so the prompts require digits; the checker cannot judge whether a claim is *reasonable*, only whether it is *supported*.

## 7. Graph (`investigation/graph.py`)

Use `reference/graph.py`. Inject the real node functions with `build_graph(nodes)`. Behavior (tested with stubs): the two helper agents run in parallel, the drafter runs once after both finish, the checker routes to `finalize_ok`, to one retry of the drafter, or to `finalize_fail`.

## 8. Service and case document (`investigation/service.py`)

`run_investigation(alert_id) -> case_id`:
1. Create the case (`status=queued`) and set the alert `investigating`.
2. Set `running`. Invoke the graph with config `{"run_id": run_uuid, "tags": [...], "metadata": {...}, "configurable": {"calls": CallCounter(MAX_LLM_CALLS_PER_CASE)}}` (see §5).
3. Persist the result. Map graph `status` to the case status. On an exception (including `CallLimitExceeded` and `TokenBudgetExceeded`, the latter reported as `llm_budget_exhausted`) set `failed` with `error`.
4. Never raise to the API caller from a background task; write the error to the case.

Case document:

```json
{"case_id": "…", "alert_id": "…", "scenario_id": "…", "status": "checked",
 "facts": [ {"id": "F1", "label": "…", "value": 14, "unit": null, "source": "…"} ],
 "typology_notes": [], "benign_notes": [], "missing_evidence": [],
 "retrieved_chunk_ids": ["c_doc1_0003_001"],
 "case_file": { "verdict": "needs_review", "summary": "…", "claims": [], "benign_explanations": [], "typology_context": [], "missing_evidence": [], "limitations": "…" },
 "checker": {"passed": true, "errors": [], "attempts": 1},
 "model_ids": {"llm": "…"}, "prompt_version": "v1",
 "langsmith_run_id": "…", "llm_calls": 3, "tokens": {"input": 0, "output": 0}, "timings": {"total_seconds": 12.4},
 "error": null, "created_at": "…", "finished_at": "…"}
```

When the status is `needs_human_rewrite`, keep the last draft in `case_file` and the checker errors in `checker.errors`. The UI shows: "The AI draft failed checks. Write the case file yourself." with the facts visible.

Idempotency: investigating the same alert again creates a new case (history is kept). The UI shows the latest case.

## 9. Code-only baseline (`investigation/triage_baseline.py`)

Purpose: show whether the LLM pipeline adds value. Uses the same facts, no LLM.

```python
CV_MAX = 0.05        # amounts almost identical
REPEAT_MIN = 0.5     # at least half of counterparties seen before

def triage(facts: dict[str, Fact]) -> str:
    f7 = facts["F7"].value
    f9 = facts["F9"].value
    if f9 and f9.get("cv") is not None and f9["cv"] <= CV_MAX and f7 is not None and f7 >= REPEAT_MIN:
        return "likely_legitimate"
    return "needs_review"
```

Tune `CV_MAX` and `REPEAT_MIN` on the **dev split only**, never on the evaluation split. Record the final values in the results table.

## 10. Tests

- Reference tests (20) keep passing.
- `test_investigation_end_to_end_with_fake_llm`: stub models return valid objects; case ends `checked`.
- `test_bad_number_then_retry_then_pass`: first draft has a wrong number; second is fixed; `checker.attempts == 2`.
- `test_gives_up_after_one_retry`: both drafts bad; status `needs_human_rewrite`.
- `test_call_limit_circuit_breaker`: `MAX_LLM_CALLS_PER_CASE=2` makes the case `failed` with a clear error.
- `test_case_fails_cleanly_when_token_budget_exhausted`: the case ends `failed` with `llm_budget_exhausted`, and no further LLM call is made.
- `test_tokens_recorded_per_case`: `llm_usage` rows exist for the case.
- **Leakage tests** (must exist):
  - `test_tools_never_return_label_keys`: `json.dumps` of every tool output contains none of `is_laundering`, `pattern_type`, `pattern_id`, `is_suspicious`, `n_laundering_tx`, `laundering`.
  - `test_tool_collection_allowlist`: `tool_collection("stg_labels")`, `("stg_pattern_blocks")`, `("alert_truth")` raise `PermissionError`.
  - `test_prompts_never_contain_label_keys`: a recording fake LLM captures every prompt in a full run; none contains a forbidden key.
  - `test_case_documents_have_no_truth_fields`.

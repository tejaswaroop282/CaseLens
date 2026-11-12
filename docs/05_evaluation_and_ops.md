# 05 — Evaluation, tests, logging, security, cost (M6 and all milestones)

## 1. Principles

- Report **only measured numbers**. Include failures.
- Evaluation code may read ground truth. Product code (tools, agents, case endpoints) may not.
- Change one thing at a time. Log `model_ids` and `prompt_version` with every result.
- LangSmith is the **only** tracing and evaluation tool. CloudWatch is not used. LangSmith is a cloud service: traces leave the machine. This is acceptable only because all data is public. Check the free plan limits first. With `LANGSMITH_TRACING=false` the evaluation scripts still run and write the same metrics from the local `cases` and `llm_usage` collections (no experiment UI).
- Evaluation is small on purpose (free-credit budget): 20 worries, 10 dev alerts, 30 evaluation alerts.

## 2. LangSmith setup

Environment: `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT=caselens`. Every LLM and graph call carries tags and metadata (`alert_id`, `scenario_id`, `prompt_version`, node name).

Datasets: create them from the JSONL files with `langsmith.Client().create_dataset` and `create_examples`. Run experiments with `Client.evaluate(target, data=dataset_name, evaluators=[...], summary_evaluators=[...], experiment_prefix=..., metadata={...}, max_concurrency=2)` (verified signature: `target, /, data, evaluators, summary_evaluators, metadata, experiment_prefix, description, max_concurrency, num_repetitions, upload_results, ...`). Keep `max_concurrency` low to avoid Bedrock throttling. Evaluators are plain Python functions returning `{"key": ..., "score": ...}`.

## 3. Eval set 1: scenario parsing

Data: `backend/app/eval/data/scenario_parse.jsonl` (20 rows; format and seed set in `docs/02`). Runner: `python -m app.eval.run_scenario_eval`.

Target function: `parse_intent(intent)` returns the spec as a dict (or an error record).

Evaluators (code):
- `schema_valid`: 1 if parsing produced a valid `ScenarioSpec`.
- `direction_match`: 1 if `direction` equals expected (`out`, `in` or `null`).
- `params_in_expectation`: 1 if every checked parameter meets `exact` or `range`; skipped for null rows.
- `correct_rejection`: for rows expecting `null`, 1 if the output is `null`.

Summary metrics: the mean of each, plus mean latency and total tokens (from traces).

## 4. Eval set 2: case files

### 4.1 Building the sets (`scripts/make_dev_split.py`)
1. Pick one approved, completed scenario with direction `out` (document its numbers). Direction `in` is evaluated for scenario metrics only (precision, pattern recall), not for case files.
2. Read `alert_truth`. Sample with `RANDOM_SEED=42`: **dev split** 10 alerts (5 suspicious, 5 not) and **eval split** 30 alerts (15 and 15), disjoint. If there are fewer suspicious alerts than needed, use all available and report the actual counts (and say so in the README).
3. Save `eval/data/case_dev.jsonl` and `case_eval.jsonl` as `{"alert_id", "is_suspicious"}`. Only evaluation code reads the truth field.
4. Use the **dev split** for prompt work and baseline tuning. Use the **eval split once** per reported configuration.

### 4.2 Systems compared
- **A. Rule only:** every alert goes to a human (no triage).
- **B. Code baseline:** `triage_baseline.triage(facts)` (no LLM).
- **C. CaseLens:** the full graph; the verdict is `case_file.verdict`; cases that end `needs_human_rewrite` or `failed` count as `needs_review`.

### 4.3 Evaluators and metrics

| Metric | Definition | Goal |
|---|---|---|
| **False-clear rate** | suspicious alerts with verdict `likely_legitimate` / suspicious alerts | **0**. Explain every exception |
| **Auto-clear rate** | non-suspicious alerts with verdict `likely_legitimate` / non-suspicious alerts | higher is better (time saved) |
| Review load | share of alerts not marked `likely_legitimate` | lower is better, never at the cost of false-clears |
| Checker first-pass rate | cases whose first draft passed | report |
| Checker after-retry pass rate | cases `checked` after at most one retry | report |
| Citation validity | share of claims whose ids exist and numbers match (re-run the checker per claim) | report |
| Needs-rewrite rate | cases ending `needs_human_rewrite` | report |
| Latency and tokens | per case, from traces | report |
| Optional faithfulness | model-as-judge score, **spot-checked by hand on 10 cases** | optional |

For system A the false-clear rate is 0 by definition and the auto-clear rate is 0; it is the reference for review load (100 percent).

### 4.4 Results table (put it in the README)

| System | n | False-clear | Auto-clear | Review load | Checker after-retry | Avg latency | Avg tokens |
|---|---|---|---|---|---|---|---|
| A. Rule only | | | | | | | |
| B. Code baseline (CV_MAX=…, REPEAT_MIN=…) | | | | | | | |
| C. CaseLens (models, prompt v…) | | | | | | | |

Add: sample sizes, scenario numbers, slice, dates, seed, and a **failures** section with 3 to 5 concrete cases (what the system said, what was true, why, and what changed afterwards).

### 4.5 Experiment hygiene
- Same alerts every run. Same seed.
- Record `PROMPT_VERSION`, model ids, `TYPOLOGY_TOP_K` in experiment metadata.
- Re-run the **dev split** after each prompt change. Run the **eval split** only for final comparisons.
- If a result looks too good, check for leakage first (`docs/03` leakage tests).

## 5. Test plan summary

| Area | Tests |
|---|---|
| Reference code | 20 tests in `reference/` (models, checker, graph, token budget, rules oracle) |
| Pipeline | `docs/01` section 8 |
| Scenario and rules | `docs/02` section 9 |
| Investigation and leakage | `docs/03` section 10 |
| API | `docs/04` section 5 |
| Eval datasets | `test_eval_files_are_valid_jsonl`, `test_dev_and_eval_splits_are_disjoint`, `test_splits_balanced_when_possible`, `test_dry_run_refuses_when_budget_too_small` |

Testing without network: provide `get_chat_model(role)` and `get_embeddings()` in `llm.py` behind a function that tests can override (dependency injection or a test fixture). Fake models return valid Pydantic objects. No test may call Bedrock, Chroma or LangSmith unless marked `@pytest.mark.integration` and skipped by default. Use a separate test database name.

Run: `pytest -q` (unit) and `pytest -q -m integration` (needs the MongoDB container and AWS).

## 6. Logging and observability

- `structlog` JSON to stdout. Fields: `ts`, `level`, `event`, `request_id`, `scenario_id`, `alert_id`, `case_id`, `node`, `duration_ms`.
- Log: pipeline step start/end with row counts; rule run duration and alert count; each graph node duration; checker errors (ids only); Bedrock retries and errors.
- Never log: credentials, full prompts, full document text, full transaction lists.
- Pipeline records in `pipeline_runs`; quality results in `dq_reports`.

## 7. Security and governance

IAM policy (least privilege; fill ARNs; check your account):

```json
{"Version": "2012-10-17",
 "Statement": [
  {"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
   "Resource": ["<chat model or inference profile ARN>", "<titan embed v2 ARN>"]},
  {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"], "Resource": "arn:aws:s3:::<bucket>/*"},
  {"Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": "arn:aws:s3:::<bucket>"}]}
```

Converse calls are normally authorized by the invoke actions. A cross-Region inference profile may need the underlying model ARNs too (check the Bedrock docs).

Controls:
- S3: block public access, default encryption, no public ACLs.
- Credentials: prefer SSO or short-lived keys. Never commit keys. `.env` is gitignored; `.env.example` has empty values.
- Tools are read-only and allow-listed. Decisions are append-only with time and analyst name.
- Record dataset licenses and sources in `docs/SOURCES.md` (IBM AML: CDLA-Sharing-1.0; PDFs: each source).
- Prompt injection: PDF text and user intent are untrusted. Outputs are schema-validated, the checker verifies claims, tools are read-only, and no tool performs actions.
- Do not claim regulatory compliance.

## 8. Cost controls (Bedrock budget $0 to $5, free credits only)

- **Hard token budget in code:** `LLM_TOKEN_BUDGET_INPUT`, `LLM_TOKEN_BUDGET_OUTPUT`, `EMBED_TOKEN_BUDGET` (defaults in `PROJECT_REPORT.md` section 9). `reference/budget.py` records each call in `llm_usage` and raises `TokenBudgetExceeded` when the budget is used up. Tests: `test_parse_stops_when_token_budget_exhausted`, `test_case_fails_cleanly_when_token_budget_exhausted`.
- **Estimate before every evaluation run:** `python -m app.eval.run_case_eval --dry-run` prints the number of cases, the estimated tokens (about 7.5k in / 1.5k out per case, plus a retry allowance; my estimate) and the remaining budget, then asks for confirmation. A run that would exceed the remaining budget refuses to start.
- **See the spend:** `python -m app.scripts.estimate_cost --price-in <USD per million input tokens> --price-out <USD per million output tokens>` sums `llm_usage`. Look up the current price of the chosen model yourself; this spec does not state prices.
- One small model, temperature 0, `LLM_MAX_TOKENS`, `MAX_LLM_CALLS_PER_CASE`, one retry only.
- Embed each PDF once; skip when `config_hash` is unchanged.
- Investigate 3 to 5 alerts by hand before running the 10 dev alerts, and use the 30 evaluation alerts only for final runs.
- `MAX_ALERTS` stops broad scenarios (which would also make many alerts to investigate).
- Check Billing → Credits before starting. Set an AWS budget alert on day one (it warns, it may not stop spending).
- **Disk (10 GB cap):** run `python -m pipeline.disk_report` after M1 and after larger steps. Routine cleanup: `docker image prune -f`, `docker builder prune -f`. Full cleanup: `docker compose down -v` (deletes the MongoDB volume), delete `data\` (includes the Chroma folder).
- Cleanup when done: delete S3 objects and the bucket, remove IAM credentials, delete the LangSmith project if wanted.

## 9. README outline (write at the end of M6)

1. What and why (plain words; the two business problems)
2. Honest scope: simulated transactions, no compliance claims
3. Architecture picture and flow
4. How to run (clone, `.env`, `docker compose up`, pipeline, UI)
5. Data sources and licenses
6. Design decisions (why code collects facts, why a checker, why labels are hidden, why Bedrock only for two jobs)
7. Results table, failures, limitations
8. Cost notes and cleanup
9. What I would do next

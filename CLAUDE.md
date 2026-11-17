# CLAUDE.md — CaseLens (prototype)

You are building CaseLens, a **small** financial-crime compliance prototype with **one suspicious pattern**: the fan pattern (one account versus many different counterparties in a time window), direction `out` or `in`. **Read `PROJECT_REPORT.md` first**, then the detail file for your milestone.

| Read | When |
|---|---|
| `PROJECT_REPORT.md` | Always: scope, decisions (D1–D16), architecture, Windows setup, repo layout, config, cost and disk budgets, milestones, pitfalls |
| `docs/01_data_pipeline.md` | M1 |
| `docs/02_scenario_studio.md` | M2, M3 |
| `docs/03_investigation_agents.md` | M4 |
| `docs/04_api_and_frontend.md` | M3, M5 |
| `docs/05_evaluation_and_ops.md` | M6, tests, logging, security, cost |
| `reference/` | Tested code to copy first: models, checker, graph, token budget, rules oracle (20 tests) |
| `architecture.png` | Layered architecture picture |

## Environment (fixed by the user)
- **Windows laptop**, 16 GB RAM, **disk under 10 GB**, nothing configured yet. Use **PowerShell** commands. Keep code cross-platform (`pathlib`; operational scripts are Python commands).
- **Only MongoDB runs in Docker.** FastAPI, the pipeline and React run directly on Windows. Chroma is **embedded** (folder `data/chroma`), not a server.
- **Model provider (D18):** Gemini API (free tier) now, chat plus embeddings; Bedrock ($0 to $5 free credits) is the planned production path behind `LLM_PROVIDER`.
- **Small real data:** IBM AML HI-Small, only two files (`HI-Small_Trans.csv`, `HI-Small_Patterns.txt`), only the first `SLICE_HOURS` hours (default 24). Never download the whole Kaggle dataset.

## What it is
- **Scenario Studio:** worry text → `ScenarioSpec` (`direction` out or in, plus numbers) → human approves → fan rule runs on real labeled data → precision, pattern recall, real examples. Any worry that is not the fan pattern is **rejected as unsupported**. Do not generalize it into a pattern solver.
- **Investigation agents:** code builds facts → typology agent (LLM + Chroma) and benign agent (LLM) in parallel → drafter (LLM) → code checker → one retry → human decides.

## Hard rules
1. **No fake data.** Real public data only. Tiny hand-made fixtures are allowed only inside tests.
2. **The LLM never writes queries or code.** It fills Pydantic schemas only.
3. **All numbers come from code** (the fact sheet). The LLM cites fact ids and copies numbers. The evidence checker verifies them.
4. **No label leakage.** Ground truth lives only in `stg_labels`, `stg_pattern_blocks`, `alert_truth`. Tools, agents, prompts and the alert/case endpoints must never read or return it. The leakage tests in `docs/03` must exist and pass.
5. **A human decides.** Never auto-close or auto-approve. Decisions are `dismiss`, `escalate`, `need_info`, append-only.
6. **Only S3, IAM and Bedrock on AWS.** Do not add other AWS services without updating `PROJECT_REPORT.md` with a stated reason.
7. **Secrets** only in `.env` (gitignored). Commit `.env.example`. Never print keys.
8. **Cost control is code, not a promise.** Every LLM and embedding call goes through the token ledger (`reference/budget.py`). Defaults: temperature 0, capped output tokens, one retry, call limit per case. Run `--dry-run` before evaluation runs. Never loop LLM calls without a cap. Try 3 to 5 alerts before larger runs.
9. **Disk cap 10 GB.** Run `python -m pipeline.disk_report` after M1 and after larger steps. Keep `KEEP_LOCAL_RAW=false`. No second copy of dependencies.
10. **Be honest in docs.** IBM transactions are simulated. Do not claim compliance. Report only measured results.
11. **Verify data assumptions** (headers, timestamp format, account-id uniqueness, patterns file shape) on the real files. Fix loaders, not files. Record findings in `docs/DATA_NOTES.md`.
12. Do not change a decision in the decision log without updating `PROJECT_REPORT.md`.
13. **Scope discipline.** No second pattern, no sanctions screening, no Guardrails, no MCP, no agent platform, no extra services. If you think something is needed, ask the user.

## Working method
- Follow M0 to M6 in order and stop at M6. Start each milestone by reading its acceptance check in `PROJECT_REPORT.md` section 13; finish by running it and reporting the output.
- Copy from `reference/` instead of rewriting; keep its 20 tests passing; change imports to package imports.
- Small commits per milestone. Tests before moving on. Unit tests use fake LLMs and fake embeddings (no network). Integration tests are marked and skipped by default.
- All settings come from `backend/app/config.py`. No hard-coded model ids, Regions or paths.
- When something is ambiguous, check `PROJECT_REPORT.md` sections 15 and 16 first. Ask the user only about: Bedrock Region and enabled model, the 3 to 5 regulatory PDFs, anything that would raise cost or disk use.

## Commands (target, PowerShell, venv active)
```
docker compose up -d mongo
python -m pipeline.slice_advice
python -m pipeline.run --step all
python -m pipeline.disk_report
pytest -q
python -m app.scripts.bedrock_smoke
uvicorn app.main:app --reload --port 8000        # from backend\
npm run dev                                       # from frontend\
python -m app.eval.run_scenario_eval
python -m app.eval.run_case_eval --dry-run
python -m app.scripts.estimate_cost --price-in <x> --price-out <y>
```

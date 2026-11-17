# CaseLens backend

FastAPI service, data pipeline and evaluation code. See the [root README](../README.md) for the project overview and
setup, and [PROJECT_REPORT.md](../PROJECT_REPORT.md) for decisions.

## Layout

| Path | What it holds |
|---|---|
| `app/main.py` | FastAPI app, error contract, startup recovery of interrupted jobs |
| `app/config.py` | The only place that reads `.env` (pydantic-settings) |
| `app/auth.py`, `app/api/auth.py` | Sign-in, HMAC session tokens, owner and analyst roles (D19) |
| `app/api/` | Routes: scenarios, alerts and cases, uploads, health and meta |
| `app/llm.py`, `app/budget.py` | Model providers (Gemini or Bedrock), token ledger with hard budgets, paced embeddings |
| `app/scenario/` | Worry → `ScenarioSpec` parsing and validation |
| `app/rules/` | The fan rule (MongoDB aggregation), run engine (all / date range / new data), metrics |
| `app/investigation/` | Fact sheet (F0–F10), prompts, LangGraph nodes, evidence checker, service |
| `app/tools/` | Read-only, allow-listed data and retrieval tools (no ground truth) |
| `app/eval/` | Evaluation sets, metrics and runners (scenario parsing; case files A/B/C) |
| `app/scripts/` | Smoke test, investigate, dev/eval split, cost estimate |
| `pipeline/` | raw → staging → labels → docs → dq, uploads, slice advice, disk report |
| `tests/` | Unit tests (fake LLM and embeddings, no network) and integration tests (MongoDB) |

## Commands (from `backend/`, venv active)

```powershell
pytest -q                          # unit tests
pytest -q -m integration           # integration tests (MongoDB container running)
python -m app.scripts.smoke        # check the configured model provider
python -m pipeline.run --step all  # build the data
uvicorn app.main:app --port 8000   # API
```

## API overview

All routes are under `/api`. `POST /auth/login` returns a bearer token; every other route except `/health` and `/meta`
needs it. Owner-only: scenario parse, edit, approve, clone, run, run-new-data, uploads. Analyst-only: investigate,
decision. Both roles: read scenarios, alerts, cases, chunks and decision counts. Errors use
`{"error": {"code", "message", "details"}}`.

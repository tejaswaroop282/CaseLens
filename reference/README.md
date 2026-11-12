# reference/

Small, tested building blocks. Copy them into the backend and extend; do not rewrite them from scratch.

| File | Copy to | What it is |
|---|---|---|
| `models.py` | `backend/app/models/` | Pydantic models: `ScenarioParams`, `ScenarioSpec` (one pattern, `direction` out or in), `Fact`, `Claim`, `CaseFile`, with validators |
| `checker.py` | `backend/app/investigation/checker.py` | The evidence checker (plain code, no LLM) |
| `graph.py` | `backend/app/investigation/graph.py` | LangGraph wiring: parallel helpers, join, checker, one retry. Nodes are injected, so tests use stubs |
| `budget.py` | `backend/app/budget.py` | Token ledger and callback that refuses AI calls once the token budget is used up (keeps the project inside the free-credit budget) |
| `rules_oracle.py` | `backend/tests/oracle.py` | Pure-pandas version of the fan rule. Test oracle for the MongoDB aggregation |
| `test_reference.py`, `test_rules_oracle.py`, `test_budget.py` | `backend/tests/` | 20 passing tests (run them first) |

Tested in isolation with: Python 3.12, pydantic 2.14, langgraph 1.2, langchain-core 1.7, pytest. The MongoDB aggregation, Bedrock calls and real usage metadata from Bedrock were not run here; verify them in M2 to M4.

The files import each other as top-level modules (`from models import ...`). After copying, change them to package imports.

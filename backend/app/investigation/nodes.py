"""Graph nodes (docs/03 section 5). Code calls tools and hands results to fixed prompts; the LLM only fills
Pydantic schemas. Every LLM call: temperature 0 and max_tokens from config, BudgetCallback, per-case call cap."""
from __future__ import annotations

import json
import threading
from typing import Any, Optional

from langchain_core.callbacks import BaseCallbackManager
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.investigation import prompts as P
from app.investigation.checker import check_case_file
from app.investigation.facts import build_fact_sheet
from app.llm import budget_callback, get_chat_model
from app.models import BenignNotes, CaseFile, Fact, TypologyNotes
from app.tools import search_reg_docs


class CallLimitExceeded(RuntimeError):
    pass


class NodeParseError(RuntimeError):
    pass


class CallCounter:
    """Per-case LLM call budget, passed via config['configurable']['calls'] (not graph state: the two parallel
    helpers would otherwise write the same key)."""

    def __init__(self, limit: int):
        self.limit, self.count = limit, 0
        self._lock = threading.Lock()

    def use(self) -> None:
        with self._lock:
            if self.count >= self.limit:
                raise CallLimitExceeded(f"MAX_LLM_CALLS_PER_CASE={self.limit} reached")
            self.count += 1


def facts_for_prompt(facts: list[dict]) -> str:
    return json.dumps([{k: f.get(k) for k in ("id", "label", "value", "unit")} for f in facts],
                      separators=(",", ":"), default=str)


def _with_budget(config: Optional[dict], node: str) -> dict:
    """Child config: keep the graph's callbacks (LangSmith tracing) and add the budget callback."""
    config = dict(config or {})
    meta = {**(config.get("metadata") or {}), "node": node}
    cb = budget_callback({"node": node, "alert_id": meta.get("alert_id"), "case_id": meta.get("case_id")})
    parent = config.get("callbacks")
    if isinstance(parent, BaseCallbackManager):
        mgr = parent.copy(); mgr.add_handler(cb, inherit=True); callbacks: Any = mgr
    else:
        callbacks = [*(parent or []), cb]
    return {"callbacks": callbacks, "tags": [*(config.get("tags") or []), "caselens", node], "metadata": meta,
            "run_name": node}


def call_structured(schema: type[BaseModel], messages: list, node: str, config: Optional[dict]) -> BaseModel:
    """One retry on structured-output failure; every attempt counts against the per-case call cap."""
    calls: CallCounter = ((config or {}).get("configurable") or {})["calls"]
    model = get_chat_model(node).with_structured_output(schema)
    last: Optional[Exception] = None
    for _ in range(2):
        calls.use()
        try:
            out = model.invoke(messages, config=_with_budget(config, node))
            if out is None:
                raise OutputParserException("no structured output")
            return out
        except (OutputParserException, ValidationError) as e:
            last = e
    raise NodeParseError(f"{node}: {type(last).__name__}: {str(last)[:200]}")


def make_nodes(db) -> dict:
    s = get_settings()

    def build_facts(state: dict) -> dict:
        facts, alert, scenario = build_fact_sheet(db, state["alert"]["alert_id"])
        return {"facts": [f.model_dump() for f in facts], "alert": alert, "scenario": scenario, "status": "running"}

    def typology_agent(state: dict, config=None) -> dict:
        d = state["alert"]["direction"]
        chunks = search_reg_docs(P.TYPOLOGY_QUERY[d], s.typology_top_k)
        ids = [c["chunk_id"] for c in chunks]
        if not chunks:
            return {"typology_notes": [], "retrieved_chunk_ids": []}       # nothing to ground on: no LLM call
        excerpts = "\n\n".join(f"[{c['chunk_id']}] ({c['title']}, page {c['page']}): {c['text']}" for c in chunks)
        human = f"Pattern: {P.PATTERN_DESCRIPTION[d]}\n\nExcerpts:\n{excerpts}"
        out = call_structured(TypologyNotes, [SystemMessage(P.TYPOLOGY_SYSTEM), HumanMessage(human)],
                              "typology_agent", config)
        return {"typology_notes": [c.model_dump() for c in out.items], "retrieved_chunk_ids": ids}

    def benign_agent(state: dict, config=None) -> dict:
        human = f"Fact sheet:\n{facts_for_prompt(state['facts'])}"
        out = call_structured(BenignNotes, [SystemMessage(P.BENIGN_SYSTEM), HumanMessage(human)],
                              "benign_agent", config)
        return {"benign_notes": [c.model_dump() for c in out.explanations], "missing_evidence": out.missing_evidence}

    def drafter(state: dict, config=None) -> dict:
        human = (f"Fact sheet:\n{facts_for_prompt(state['facts'])}\n\n"
                 f"Typology notes:\n{json.dumps(state.get('typology_notes', []))}\n\n"
                 f"Harmless explanations:\n{json.dumps(state.get('benign_notes', []))}\n\n"
                 f"Missing evidence noted so far:\n{json.dumps(state.get('missing_evidence', []))}")
        messages = [SystemMessage(P.DRAFTER_SYSTEM), HumanMessage(human)]
        n = state.get("draft_count", 0)
        if n >= 1 and state.get("checker_errors"):                          # the one retry
            messages += [AIMessage(json.dumps(state.get("draft"))),
                         HumanMessage(P.RETRY_MESSAGE.format(errors="; ".join(state["checker_errors"])))]
        out = call_structured(CaseFile, messages, "drafter", config)
        return {"draft": out.model_dump(), "draft_count": n + 1, "retries": n}

    def evidence_checker(state: dict) -> dict:
        res = check_case_file(CaseFile.model_validate(state["draft"]),
                              [Fact.model_validate(f) for f in state["facts"]],
                              set(state.get("retrieved_chunk_ids") or []), id_pattern=s.id_pattern)
        return {"checker_errors": res.errors}

    return {"build_facts": build_facts, "typology_agent": typology_agent, "benign_agent": benign_agent,
            "drafter": drafter, "evidence_checker": evidence_checker}

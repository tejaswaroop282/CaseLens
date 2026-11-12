from __future__ import annotations
from typing import Any, Optional, TypedDict
from langgraph.graph import StateGraph, START, END

class State(TypedDict, total=False):
    alert: dict
    scenario: dict
    facts: list
    typology_notes: list
    retrieved_chunk_ids: list
    benign_notes: list
    missing_evidence: list
    draft: Optional[dict]
    draft_count: int       # drafter reads it, writes draft_count + 1 and retries = previous draft_count
    checker_errors: list
    retries: int           # number of retries already used (0 after the first draft)
    status: str            # "queued","running","checked","needs_human_rewrite"

MAX_RETRIES = 1

def build_graph(nodes: dict):
    g = StateGraph(State)
    for name, fn in nodes.items(): g.add_node(name, fn)
    g.add_edge(START, "build_facts")
    g.add_edge("build_facts", "typology_agent")
    g.add_edge("build_facts", "benign_agent")
    g.add_edge(["typology_agent", "benign_agent"], "drafter")     # join: wait for both
    g.add_edge("drafter", "evidence_checker")
    def route(state: State) -> str:
        if not state.get("checker_errors"): return "ok"
        return "retry" if state.get("retries", 0) <= MAX_RETRIES - 1 else "give_up"
    g.add_conditional_edges("evidence_checker", route,
                            {"ok": "finalize_ok", "retry": "drafter", "give_up": "finalize_fail"})
    g.add_node("finalize_ok", lambda s: {"status": "checked"})
    g.add_node("finalize_fail", lambda s: {"status": "needs_human_rewrite"})
    g.add_edge("finalize_ok", END); g.add_edge("finalize_fail", END)
    return g.compile()

"""Run one investigation (docs/03 section 8). The graph never closes an alert; a human decides."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.budget import TokenBudgetExceeded
from app.config import get_settings
from app.errors import InvalidState, NotFound
from app.investigation.facts import AlertNotFound
from app.investigation.graph import build_graph
from app.investigation.nodes import CallCounter, CallLimitExceeded, NodeParseError, make_nodes
from app.logging import get_logger

log = get_logger("investigation")
ACTIVE = ("queued", "running")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def start_investigation(db, alert_id: str) -> str:
    """Create a queued case (sync). 409 if a case for this alert is already queued or running."""
    alert = db.alerts.find_one({"alert_id": alert_id}, {"_id": 0, "alert_id": 1, "scenario_id": 1})
    if alert is None:
        raise NotFound(f"alert {alert_id} not found")
    if db.cases.find_one({"alert_id": alert_id, "status": {"$in": list(ACTIVE)}}):
        raise InvalidState("a case for this alert is already queued or running")
    s = get_settings()
    case_id = uuid.uuid4().hex
    db.cases.insert_one({
        "case_id": case_id, "alert_id": alert_id, "scenario_id": alert["scenario_id"], "status": "queued",
        "facts": [], "typology_notes": [], "benign_notes": [], "missing_evidence": [], "retrieved_chunk_ids": [],
        "case_file": None, "checker": None, "model_ids": {"llm": s.bedrock_llm_id, "embed": s.bedrock_embed_id},
        "prompt_version": s.prompt_version, "langsmith_run_id": None, "llm_calls": 0,
        "tokens": {"input": 0, "output": 0}, "timings": {}, "error": None, "created_at": _now(), "finished_at": None})
    db.alerts.update_one({"alert_id": alert_id}, {"$set": {"status": "investigating"}})
    return case_id


def _tokens_for_case(db, case_id: str) -> dict:
    rows = list(db.llm_usage.aggregate([{"$match": {"case_id": case_id}},
                                        {"$group": {"_id": None, "i": {"$sum": "$input_tokens"},
                                                    "o": {"$sum": "$output_tokens"}}}]))
    return {"input": rows[0]["i"], "output": rows[0]["o"]} if rows else {"input": 0, "output": 0}


def execute_investigation(db, case_id: str) -> dict:
    """Never raises: errors are written to the case."""
    s = get_settings()
    case = db.cases.find_one({"case_id": case_id})
    t0 = time.time()
    run_id = uuid.uuid4()
    calls = CallCounter(s.max_llm_calls_per_case)
    db.cases.update_one({"case_id": case_id}, {"$set": {"status": "running", "langsmith_run_id": str(run_id)}})
    update: dict = {}
    try:
        graph = build_graph(make_nodes(db))
        out = graph.invoke(
            {"alert": {"alert_id": case["alert_id"]}, "retries": 0, "draft_count": 0},
            config={"run_id": run_id, "run_name": "investigation", "tags": ["caselens", "investigation"],
                    "metadata": {"alert_id": case["alert_id"], "scenario_id": case["scenario_id"],
                                 "case_id": case_id, "prompt_version": s.prompt_version},
                    "configurable": {"calls": calls}})
        errors = out.get("checker_errors") or []
        update = {"status": out["status"], "facts": out.get("facts", []),
                  "typology_notes": out.get("typology_notes", []), "benign_notes": out.get("benign_notes", []),
                  "missing_evidence": out.get("missing_evidence", []),
                  "retrieved_chunk_ids": out.get("retrieved_chunk_ids", []), "case_file": out.get("draft"),
                  "checker": {"passed": not errors, "errors": errors, "attempts": out.get("draft_count", 0)}}
    except Exception as e:
        code = ("llm_budget_exhausted" if isinstance(e, TokenBudgetExceeded) else
                "call_limit_exceeded" if isinstance(e, CallLimitExceeded) else
                "llm_parse_failed" if isinstance(e, NodeParseError) else
                "alert_not_found" if isinstance(e, AlertNotFound) else "investigation_failed")
        update = {"status": "failed", "error": {"code": code, "message": str(e)[:500]}}
        log.warning("investigation_failed", case_id=case_id, alert_id=case["alert_id"], error=code)
    update.update({"llm_calls": calls.count, "tokens": _tokens_for_case(db, case_id),
                   "timings": {"total_seconds": round(time.time() - t0, 2)}, "finished_at": _now()})
    db.cases.update_one({"case_id": case_id}, {"$set": update})
    log.info("investigation_done", case_id=case_id, status=update["status"], llm_calls=calls.count,
             duration_ms=int((time.time() - t0) * 1000))
    return db.cases.find_one({"case_id": case_id}, {"_id": 0})


def run_investigation(db, alert_id: str) -> str:
    case_id = start_investigation(db, alert_id)
    execute_investigation(db, case_id)
    return case_id


def latest_case(db, alert_id: str) -> Optional[dict]:
    return db.cases.find_one({"alert_id": alert_id}, {"_id": 0}, sort=[("created_at", -1)])

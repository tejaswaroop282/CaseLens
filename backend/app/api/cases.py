"""Alerts, cases, chunks, decisions and the mock downstream case system (docs/04 section 2).

Truth rule: none of these endpoints returns ground truth. Alerts never carry it; responses are additionally
stripped of truth keys as a second safety net."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field

from app.api.common import database, jsonable, run_job
from app.config import get_settings
from app.errors import InvalidState, NotFound, ValidationFailed
from app.investigation.service import execute_investigation, latest_case, start_investigation
from app.logging import get_logger

log = get_logger("api.cases")
router = APIRouter(tags=["alerts and cases"])
TRUTH_KEYS = {"is_laundering", "pattern_type", "pattern_id", "is_suspicious", "n_laundering_tx"}
DECIDABLE = ("checked", "needs_human_rewrite", "failed")


def strip_truth(v):
    if isinstance(v, dict):
        return {k: strip_truth(x) for k, x in v.items() if k not in TRUTH_KEYS}
    if isinstance(v, list):
        return [strip_truth(x) for x in v]
    return v


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _case_summary(c: Optional[dict]) -> Optional[dict]:
    if not c:
        return None
    return {"case_id": c["case_id"], "status": c["status"], "verdict": (c.get("case_file") or {}).get("verdict")}


# ---------------- alerts ----------------
@router.get("/alerts")
def list_alerts(scenario_id: Optional[str] = None, status: Optional[str] = None, page: int = Query(1, ge=1),
                page_size: int = Query(50, ge=1, le=200), db=Depends(database)):
    q = {k: v for k, v in {"scenario_id": scenario_id, "status": status}.items() if v}
    total = db.alerts.count_documents(q)
    items = list(db.alerts.find(q, {"_id": 0, "tx_ids": 0}).sort([("distinct_counterparties", -1), ("alert_id", 1)])
                 .skip((page - 1) * page_size).limit(page_size))
    latest: dict = {}
    for c in db.cases.find({"alert_id": {"$in": [a["alert_id"] for a in items]}},
                           {"_id": 0, "case_id": 1, "alert_id": 1, "status": 1, "case_file.verdict": 1, "created_at": 1}
                           ).sort("created_at", 1):
        latest[c["alert_id"]] = c                                  # ascending sort: last one wins
    for a in items:
        a["latest_case"] = _case_summary(latest.get(a["alert_id"]))
    return jsonable(strip_truth({"items": items, "page": page, "page_size": page_size, "total": total}))


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: str, db=Depends(database)):
    a = db.alerts.find_one({"alert_id": alert_id}, {"_id": 0})
    if a is None:
        raise NotFound(f"alert {alert_id} not found")
    a["latest_case"] = _case_summary(latest_case(db, alert_id))
    return jsonable(strip_truth(a))


@router.post("/alerts/{alert_id}/investigate", status_code=202)
def investigate(alert_id: str, background: BackgroundTasks, db=Depends(database)):
    case_id = start_investigation(db, alert_id)
    background.add_task(run_job, "investigation", execute_investigation, db, case_id)
    return {"case_id": case_id, "status": "queued"}


# ---------------- cases ----------------
@router.get("/cases/{case_id}")
def get_case(case_id: str, db=Depends(database)):
    c = db.cases.find_one({"case_id": case_id}, {"_id": 0})
    if c is None:
        raise NotFound(f"case {case_id} not found")
    c["decision"] = db.decisions.find_one({"case_id": case_id}, {"_id": 0}, sort=[("decided_at", -1)])
    c["alert"] = db.alerts.find_one({"alert_id": c["alert_id"]}, {"_id": 0, "tx_ids": 0})
    return jsonable(strip_truth(c))


@router.get("/chunks/{chunk_id}")
def get_chunk(chunk_id: str):
    from app.tools import get_chunk as tool_get_chunk
    ch = tool_get_chunk(chunk_id)
    if ch is None:
        raise NotFound(f"chunk {chunk_id} not found")
    return ch


class DecisionBody(BaseModel):
    decision: Literal["dismiss", "escalate", "need_info"]
    reason: str = Field(min_length=3, max_length=1000)
    analyst: str = Field(min_length=1, max_length=100)


def forward_to_case_system(doc: dict) -> dict:
    """POST the decision to the (mock) downstream system. 3 s timeout; failure is logged, never raised."""
    payload = {k: doc[k] for k in ("case_id", "alert_id", "decision", "reason", "analyst")}
    payload["decided_at"] = jsonable(doc["decided_at"])
    try:
        r = httpx.post(f"{get_settings().api_base_url}/api/mock-case-system/cases", json=payload, timeout=3.0)
        r.raise_for_status()
        return {"ok": True, "status_code": r.status_code, "external_id": r.json().get("external_id")}
    except Exception as e:
        log.warning("mock_case_system_forward_failed", case_id=doc["case_id"], error=type(e).__name__)
        return {"ok": False, "error": type(e).__name__}


@router.post("/cases/{case_id}/decision", status_code=201)
def decide(case_id: str, body: DecisionBody, db=Depends(database)):
    if not body.reason.strip() or not body.analyst.strip():
        raise ValidationFailed("reason and analyst are required")
    c = db.cases.find_one({"case_id": case_id})
    if c is None:
        raise NotFound(f"case {case_id} not found")
    if c["status"] not in DECIDABLE:
        raise InvalidState(f"case is {c['status']}; a decision needs one of {list(DECIDABLE)}")
    doc = {"decision_id": uuid.uuid4().hex, "case_id": case_id, "alert_id": c["alert_id"], "decision": body.decision,
           "reason": body.reason.strip(), "analyst": body.analyst.strip(), "decided_at": _now(),
           "ai_verdict": (c.get("case_file") or {}).get("verdict"), "case_status_at_decision": c["status"]}
    db.decisions.insert_one(dict(doc))                                      # append-only
    res = db.cases.update_one({"case_id": case_id, "status": c["status"]}, {"$set": {"status": "decided"}})
    if res.modified_count != 1:
        raise InvalidState("case changed state concurrently")
    db.alerts.update_one({"alert_id": c["alert_id"]}, {"$set": {"status": "reviewed"}})
    ack = forward_to_case_system(doc)
    db.decisions.update_one({"decision_id": doc["decision_id"]}, {"$set": {"mock_case_system": ack}})
    doc["mock_case_system"] = ack
    return jsonable(doc)


@router.get("/decisions/summary")
def decision_summary(scenario_id: Optional[str] = None, db=Depends(database)):
    match = {}
    if scenario_id:
        match["alert_id"] = {"$in": db.alerts.distinct("alert_id", {"scenario_id": scenario_id})}
    counts = {r["_id"]: r["n"] for r in db.decisions.aggregate([{"$match": match},
                                                                 {"$group": {"_id": "$decision", "n": {"$sum": 1}}}])}
    return {d: counts.get(d, 0) for d in ("dismiss", "escalate", "need_info")}


# ---------------- mock downstream case system ----------------
class MockCase(BaseModel):
    case_id: str
    alert_id: str
    decision: Literal["dismiss", "escalate", "need_info"]
    reason: str
    analyst: str
    decided_at: str


@router.post("/mock-case-system/cases", status_code=201)
def mock_receive(body: MockCase, db=Depends(database)):
    doc = {**body.model_dump(), "external_id": f"EXT-{uuid.uuid4().hex[:8].upper()}", "received_at": _now()}
    db.mock_case_system.insert_one(dict(doc))
    return jsonable(doc)


@router.get("/mock-case-system/cases")
def mock_list(db=Depends(database)):
    return jsonable({"items": list(db.mock_case_system.find({}, {"_id": 0}).sort("received_at", -1).limit(200))})

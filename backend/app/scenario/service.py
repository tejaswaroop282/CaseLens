"""Scenario Studio service: parse -> draft -> (patch) -> approve -> run; clone; examples."""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import ValidationError

from app.config import get_settings
from app.errors import InvalidState, NotFound, ValidationFailed
from app.models import ScenarioParams, ScenarioSpec
from app.scenario.parse import MAX_INTENT_CHARS, parse_intent

ALERT_SUMMARY_FIELDS = ("alert_id", "account_id", "direction", "window_start", "window_end",
                        "distinct_counterparties", "tx_count", "first_ts", "last_ts")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------- data context ----------------
def data_context(db) -> tuple[int, list[str]]:
    """(slice_hours, valid payment formats). Requires the pipeline to have run."""
    meta = db.pipeline_meta.find_one({"_id": "meta"})
    if meta is None:
        raise InvalidState("no data loaded yet; run the pipeline first", code="data_not_loaded")
    return int(meta["slice_hours"]), sorted(db.stg_transactions.distinct("payment_format"))


# ---------------- validation ----------------
def check_intent(text: Optional[str]) -> str:
    t = (text or "").strip()
    if not t:
        raise ValidationFailed("intent_text is empty")
    if len(t) > MAX_INTENT_CHARS:
        raise ValidationFailed(f"intent_text is longer than {MAX_INTENT_CHARS} characters",
                               code="intent_too_long", details={"length": len(t)})
    return t


def spec_problems(spec: ScenarioSpec, slice_hours: int, formats: list[str]) -> list[dict]:
    """Checks that need config or the database (docs/02 section 2). Empty list = valid."""
    if spec.direction is None or spec.params is None:
        return []
    out = []
    if spec.params.window_hours > slice_hours:
        out.append({"code": "window_longer_than_data",
                    "message": f"window_hours {spec.params.window_hours} is longer than the loaded data "
                               f"({slice_hours} hours)", "details": {"slice_hours": slice_hours}})
    bad = [f for f in (spec.params.payment_formats or []) if f not in formats]
    if bad:
        out.append({"code": "unknown_payment_format", "message": f"unknown payment formats: {bad}",
                    "details": {"unknown": bad, "valid": formats}})
    return out


def raise_if_problems(problems: list[dict]) -> None:
    if problems:
        p = problems[0]
        raise ValidationFailed(p["message"], code=p["code"], details={**p["details"], "all": problems})


# ---------------- reads ----------------
def get(db, scenario_id: str) -> dict:
    sc = db.scenarios.find_one({"scenario_id": scenario_id}, {"_id": 0})
    if sc is None:
        raise NotFound(f"scenario {scenario_id} not found")
    run = db.rule_runs.find_one({"scenario_id": scenario_id}, {"_id": 0}, sort=[("started_at", -1)])
    sc["latest_run"] = ({k: run.get(k) for k in ("run_id", "status", "error", "metrics", "started_at", "finished_at",
                                                 "mode", "range_start", "range_end")} if run else None)
    sc["run_count"] = db.rule_runs.count_documents({"scenario_id": scenario_id})
    return sc


def list_scenarios(db, page: int, page_size: int) -> dict:
    total = db.scenarios.count_documents({})
    items = list(db.scenarios.find({}, {"_id": 0}).sort("created_at", -1)
                 .skip((page - 1) * page_size).limit(page_size))
    return {"items": items, "page": page, "page_size": page_size, "total": total}


# ---------------- writes ----------------
def create_from_intent(db, intent_text: str) -> dict:
    text = check_intent(intent_text)
    slice_hours, formats = data_context(db)
    s = get_settings()
    scenario_id = uuid.uuid4().hex
    spec = parse_intent(text, formats, slice_hours, metadata={"scenario_id": scenario_id})
    doc = {"scenario_id": scenario_id, "intent_text": text, "spec": spec.model_dump(), "status": "draft",
           "validation_problems": spec_problems(spec, slice_hours, formats),
           "created_at": _now(), "approved_at": None, "approved_by": None,
           "parse_meta": {"model_id": s.llm_model_id, "prompt_version": s.prompt_version,
                          "langsmith_run_id": None}}
    db.scenarios.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


def _require(db, scenario_id: str, status: str) -> dict:
    sc = db.scenarios.find_one({"scenario_id": scenario_id})
    if sc is None:
        raise NotFound(f"scenario {scenario_id} not found")
    if sc["status"] != status:
        raise InvalidState(f"scenario is {sc['status']}; this action needs {status}")
    return sc


def patch(db, scenario_id: str, direction: Optional[str], params: Optional[dict]) -> dict:
    """Only drafts with a supported direction; only direction and params; fully revalidated."""
    sc = _require(db, scenario_id, "draft")
    old = ScenarioSpec.model_validate(sc["spec"])
    if old.direction is None:
        raise InvalidState("this worry was rejected as unsupported; write a new worry instead")
    if direction is None and params is None:
        raise ValidationFailed("nothing to change: send direction and/or params")
    merged = {**(old.params.model_dump() if old.params else {}), **(params or {})}
    try:
        new_params = ScenarioParams.model_validate(merged)
        new = old.model_copy(update={"direction": direction or old.direction, "params": new_params})
        new = ScenarioSpec.model_validate(new.model_dump())
    except ValidationError as e:
        raise ValidationFailed("invalid scenario values", details={"errors": e.errors(include_url=False)})
    slice_hours, formats = data_context(db)
    raise_if_problems(spec_problems(new, slice_hours, formats))
    db.scenarios.update_one({"scenario_id": scenario_id, "status": "draft"},
                            {"$set": {"spec": new.model_dump(), "validation_problems": [],
                                      "updated_at": _now()}})
    return get(db, scenario_id)


def approve(db, scenario_id: str, approved_by: Optional[str]) -> dict:
    who = (approved_by or "").strip()
    if not who:
        raise ValidationFailed("approved_by is required")
    sc = _require(db, scenario_id, "draft")
    spec = ScenarioSpec.model_validate(sc["spec"])
    if spec.direction is None:
        raise InvalidState("unsupported worries cannot be approved", details={"reason": spec.unsupported_reason})
    slice_hours, formats = data_context(db)
    problems = spec_problems(spec, slice_hours, formats)
    if problems:
        raise InvalidState("fix the scenario before approving", details={"problems": problems})
    at = _now()
    res = db.scenarios.update_one({"scenario_id": scenario_id, "status": "draft"},
                                  {"$set": {"status": "approved", "approved_at": at, "approved_by": who}})
    if res.modified_count != 1:
        raise InvalidState("scenario changed state concurrently")
    return {"scenario_id": scenario_id, "status": "approved", "approved_at": at, "approved_by": who}


def clone(db, scenario_id: str) -> dict:
    sc = db.scenarios.find_one({"scenario_id": scenario_id}, {"_id": 0})
    if sc is None:
        raise NotFound(f"scenario {scenario_id} not found")
    new = {"scenario_id": uuid.uuid4().hex, "intent_text": sc["intent_text"], "spec": sc["spec"],
           "status": "draft", "validation_problems": sc.get("validation_problems", []),
           "created_at": _now(), "approved_at": None, "approved_by": None,
           "parse_meta": sc.get("parse_meta"), "cloned_from": scenario_id}
    db.scenarios.insert_one(dict(new))
    return new


# ---------------- examples (the ONE place that shows truth; docs/02 section 7) ----------------
def examples(db, scenario_id: str, k: int = 5) -> dict:
    get(db, scenario_id)
    run = db.rule_runs.find_one({"scenario_id": scenario_id, "status": "completed"}, sort=[("started_at", -1)])
    if run is None:
        return {"hits": [], "look_alikes": []}
    truth = {t["alert_id"]: t for t in db.alert_truth.find({"scenario_id": scenario_id}, {"_id": 0})}
    alerts = list(db.alerts.find({"scenario_id": scenario_id, "run_id": run["run_id"]},
                                 {"_id": 0, **{f: 1 for f in ALERT_SUMMARY_FIELDS}, "tx_ids": 1}))
    alerts.sort(key=lambda a: a["alert_id"])                       # stable order before seeded sampling
    rnd = random.Random(get_settings().random_seed)
    hits = [a for a in alerts if truth.get(a["alert_id"], {}).get("is_suspicious")]
    looks = [a for a in alerts if not truth.get(a["alert_id"], {}).get("is_suspicious")]
    pick = lambda xs: rnd.sample(xs, min(k, len(xs)))              # noqa: E731

    def item(a: dict) -> dict:
        types = sorted({d.get("pattern_type") for d in db.stg_labels.find(
            {"tx_id": {"$in": a.get("tx_ids", [])}}, {"pattern_type": 1})} - {None})
        return {**{f: a.get(f) for f in ALERT_SUMMARY_FIELDS}, "is_suspicious": truth[a["alert_id"]]["is_suspicious"],
                "n_laundering_tx": truth[a["alert_id"]]["n_laundering_tx"], "pattern_types": types}
    return {"hits": [item(a) for a in pick(hits)], "look_alikes": [item(a) for a in pick(looks)]}

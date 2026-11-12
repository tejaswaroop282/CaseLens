"""Scenario Studio endpoints (docs/04 section 2)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel

from app.api.common import database, jsonable, run_job
from app.errors import InvalidState, ValidationFailed
from app.rules.engine import RangeError, ScenarioStateError, execute_run, start_run
from app.scenario import service

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


class ParseBody(BaseModel):
    intent_text: Optional[str] = None


class PatchBody(BaseModel):
    direction: Optional[Literal["out", "in"]] = None
    params: Optional[dict] = None


class ApproveBody(BaseModel):
    approved_by: Optional[str] = None


@router.post("/parse", status_code=201)
def parse(body: ParseBody, db=Depends(database)):
    return jsonable(service.create_from_intent(db, body.intent_text))


@router.get("")
def list_(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), db=Depends(database)):
    return jsonable(service.list_scenarios(db, page, page_size))


@router.get("/{scenario_id}")
def get(scenario_id: str, db=Depends(database)):
    return jsonable(service.get(db, scenario_id))


@router.patch("/{scenario_id}")
def patch(scenario_id: str, body: PatchBody, db=Depends(database)):
    return jsonable(service.patch(db, scenario_id, body.direction, body.params))


@router.post("/{scenario_id}/approve")
def approve(scenario_id: str, body: ApproveBody, db=Depends(database)):
    return jsonable(service.approve(db, scenario_id, body.approved_by))


@router.post("/{scenario_id}/clone", status_code=201)
def clone(scenario_id: str, db=Depends(database)):
    return jsonable(service.clone(db, scenario_id))


class RunBody(BaseModel):
    mode: Literal["all", "range", "new"] = "all"
    start: Optional[datetime] = None
    end: Optional[datetime] = None


def _start(db, scenario_id: str, body: RunBody) -> str:
    try:
        return start_run(db, scenario_id, body.mode, body.start, body.end)
    except ScenarioStateError as e:
        raise InvalidState(str(e))
    except RangeError as e:
        raise ValidationFailed(str(e), code="invalid_range")


@router.post("/run-new-data", status_code=202)
def run_all_on_new_data(background: BackgroundTasks, db=Depends(database)):
    """After an upload: run every completed scenario on its new, complete windows (D17)."""
    started, skipped = [], []
    for sc in db.scenarios.find({"status": "completed"}, {"scenario_id": 1, "intent_text": 1}):
        try:
            run_id = start_run(db, sc["scenario_id"], "new")
        except (ScenarioStateError, RangeError) as e:
            skipped.append({"scenario_id": sc["scenario_id"], "reason": str(e)})
            continue
        background.add_task(run_job, "rule_run", execute_run, db, sc["scenario_id"], run_id)
        started.append({"scenario_id": sc["scenario_id"], "run_id": run_id})
    return {"started": started, "skipped": skipped}


@router.post("/{scenario_id}/run", status_code=202)
def run(scenario_id: str, background: BackgroundTasks, body: Optional[RunBody] = None, db=Depends(database)):
    service.get(db, scenario_id)                                   # 404 if missing
    run_id = _start(db, scenario_id, body or RunBody())
    background.add_task(run_job, "rule_run", execute_run, db, scenario_id, run_id)
    return {"run_id": run_id, "status": "running"}


@router.get("/{scenario_id}/runs")
def runs(scenario_id: str, db=Depends(database)):
    service.get(db, scenario_id)
    return jsonable({"items": list(db.rule_runs.find({"scenario_id": scenario_id}, {"_id": 0}).sort("started_at", -1))})


@router.get("/{scenario_id}/examples")
def examples(scenario_id: str, k: int = Query(5, ge=1, le=20), db=Depends(database)):
    """The only endpoint that returns ground truth (an analysis view for the risk owner)."""
    return jsonable(service.examples(db, scenario_id, k))

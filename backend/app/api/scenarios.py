"""Scenario Studio endpoints (docs/04 section 2)."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel

from app.api.common import database, jsonable, run_job
from app.rules.engine import ScenarioStateError, execute_run, start_run
from app.errors import InvalidState
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


@router.post("/{scenario_id}/run", status_code=202)
def run(scenario_id: str, background: BackgroundTasks, db=Depends(database)):
    service.get(db, scenario_id)                                   # 404 if missing
    try:
        run_id = start_run(db, scenario_id)
    except ScenarioStateError as e:
        raise InvalidState(str(e))
    background.add_task(run_job, "rule_run", execute_run, db, scenario_id, run_id)
    return {"run_id": run_id, "status": "running"}


@router.get("/{scenario_id}/examples")
def examples(scenario_id: str, k: int = Query(5, ge=1, le=20), db=Depends(database)):
    """The only endpoint that returns ground truth (an analysis view for the risk owner)."""
    return jsonable(service.examples(db, scenario_id, k))

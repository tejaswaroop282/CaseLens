"""Run one approved scenario: fan rule -> alerts (no truth) -> alert_truth -> metrics (docs/02 section 5)."""
from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import get_settings
from app.logging import get_logger
from app.models import ScenarioSpec
from app.rules.fan import build_pipeline
from app.rules.metrics import alert_truth, compute_metrics

log = get_logger("rules")

MAX_STORED_TX_IDS = 500
INSERT_BATCH = 1000


class ScenarioStateError(Exception):
    """Scenario is not in a state that allows this action (HTTP 409 invalid_state)."""


class TooManyAlerts(Exception):
    pass


def make_alert_id(scenario_id: str, account_id: str, direction: str, window_start: datetime) -> str:
    iso = window_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return hashlib.sha1(f"{scenario_id}|{account_id}|{direction}|{iso}".encode()).hexdigest()[:16]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def start_run(db, scenario_id: str) -> str:
    """Move an approved scenario to running and create its rule_runs document (sync; the API calls this
    before scheduling execute_run in the background)."""
    res = db.scenarios.find_one_and_update({"scenario_id": scenario_id, "status": "approved"},
                                           {"$set": {"status": "running"}})
    if res is None:
        sc = db.scenarios.find_one({"scenario_id": scenario_id}, {"status": 1})
        raise ScenarioStateError(f"scenario is {sc['status'] if sc else 'missing'}; only approved scenarios can run")
    run_id = uuid.uuid4().hex
    db.rule_runs.insert_one({"run_id": run_id, "scenario_id": scenario_id, "status": "running",
                             "started_at": _now(), "finished_at": None, "error": None, "metrics": None})
    return run_id


def execute_run(db, scenario_id: str, run_id: str, max_alerts: Optional[int] = None) -> dict:
    """Never raises for rule errors: writes failed + error to rule_runs and the scenario."""
    s = get_settings()
    max_alerts = max_alerts or s.max_alerts
    t0 = time.time()
    try:
        sc = db.scenarios.find_one({"scenario_id": scenario_id})
        spec = ScenarioSpec.model_validate(sc["spec"])
        meta = db.pipeline_meta.find_one({"_id": "meta"})
        if meta is None:
            raise RuntimeError("no data loaded (pipeline_meta missing); run the pipeline first")
        origin, slice_end = meta["data_origin"], meta["slice_end"]
        p = spec.params
        pipeline = build_pipeline(spec.direction, p, origin, slice_end)

        rows = []
        for row in db.stg_transactions.aggregate(pipeline, allowDiskUse=True, batchSize=1000):
            rows.append(row)
            if len(rows) > max_alerts:
                raise TooManyAlerts(f"more than {max_alerts} alerts; tighten the numbers "
                                    "(raise min_counterparties or shorten window_hours)")

        laundering = {d["tx_id"] for d in db.stg_labels.find({}, {"tx_id": 1, "_id": 0})}
        blocks = list(db.stg_pattern_blocks.find({}, {"_id": 0, "pattern_type": 1, "tx_ids": 1}))
        alerts, truths, full_lists = [], [], []
        created = _now()
        for r in rows:
            ws = origin + timedelta(hours=r["bucket"] * p.window_hours)
            aid = make_alert_id(scenario_id, r["account_id"], spec.direction, ws)
            full = sorted(r["tx_ids"])
            full_lists.append(full)
            alerts.append({
                "alert_id": aid, "scenario_id": scenario_id, "run_id": run_id, "direction": spec.direction,
                "account_id": r["account_id"], "bucket": r["bucket"], "window_hours": p.window_hours,
                "window_start": ws, "window_end": ws + timedelta(hours=p.window_hours),
                "distinct_counterparties": r["distinct_counterparties"], "tx_count": r["tx_count"],
                "tx_ids": full[:MAX_STORED_TX_IDS], "tx_ids_truncated": len(full) > MAX_STORED_TX_IDS,
                "first_ts": r["first_ts"], "last_ts": r["last_ts"], "status": "new", "created_at": created})
            truths.append({"alert_id": aid, "scenario_id": scenario_id, **alert_truth(full, laundering)})
        for i in range(0, len(alerts), INSERT_BATCH):
            db.alerts.insert_many(alerts[i:i + INSERT_BATCH], ordered=False)
            db.alert_truth.insert_many(truths[i:i + INSERT_BATCH], ordered=False)   # truth never on alerts

        metrics = compute_metrics(spec.direction, full_lists, laundering, blocks, meta["slice_hours"],
                                  time.time() - t0)
        db.rule_runs.update_one({"run_id": run_id}, {"$set": {"status": "completed", "metrics": metrics,
                                                              "finished_at": _now()}})
        db.scenarios.update_one({"scenario_id": scenario_id}, {"$set": {"status": "completed"}})
        log.info("rule_run_completed", scenario_id=scenario_id, run_id=run_id, alerts=len(alerts),
                 duration_ms=int((time.time() - t0) * 1000))
        return metrics
    except Exception as e:
        code = "too_many_alerts" if isinstance(e, TooManyAlerts) else "rule_run_failed"
        err = {"code": code, "message": str(e)}
        db.rule_runs.update_one({"run_id": run_id}, {"$set": {"status": "failed", "error": err,
                                                              "finished_at": _now()}})
        db.scenarios.update_one({"scenario_id": scenario_id}, {"$set": {"status": "failed"}})
        log.warning("rule_run_failed", scenario_id=scenario_id, run_id=run_id, error=code)
        return {"error": err}


def run_scenario(db, scenario_id: str, max_alerts: Optional[int] = None) -> dict:
    return execute_run(db, scenario_id, start_run(db, scenario_id), max_alerts)

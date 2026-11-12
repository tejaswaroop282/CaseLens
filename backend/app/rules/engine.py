"""Run a scenario: fan rule -> alerts (no truth) -> alert_truth -> metrics (docs/02 section 5, D17).

Run modes (D17): "all" (all loaded data), "range" (a date range), "new" (data after the scenario's
covered_until). Ranges are aligned to whole windows counted from data_origin: a window is evaluated only when
it is complete. Alerts that already exist for the scenario are never created twice."""
from __future__ import annotations

import hashlib
import math
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
MODES = ("all", "range", "new")


class ScenarioStateError(Exception):
    """Scenario is not in a state that allows this action (HTTP 409 invalid_state)."""


class TooManyAlerts(Exception):
    pass


class RangeError(Exception):
    pass


def make_alert_id(scenario_id: str, account_id: str, direction: str, window_start: datetime) -> str:
    iso = window_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return hashlib.sha1(f"{scenario_id}|{account_id}|{direction}|{iso}".encode()).hexdigest()[:16]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def aligned_range(origin: datetime, data_end: datetime, window_hours: int, start: Optional[datetime],
                  end: Optional[datetime]) -> tuple[datetime, datetime]:
    """Snap [start, end) inward to whole windows inside [origin, data_end)."""
    w = timedelta(hours=window_hours)
    start = max(start or origin, origin)
    end = min(end or data_end, data_end)
    sb = math.ceil((start - origin) / w)
    eb = math.floor((end - origin) / w)
    rs, re_ = origin + sb * w, origin + eb * w
    if re_ <= rs:
        raise RangeError(f"the range holds no complete {window_hours}-hour window "
                         f"(windows start at {origin:%Y-%m-%d %H:%M} UTC; data ends {data_end:%Y-%m-%d %H:%M} UTC)")
    return rs, re_


def start_run(db, scenario_id: str, mode: str = "all", start: Optional[datetime] = None,
              end: Optional[datetime] = None) -> str:
    """Validate and claim the scenario (sync), resolve the range, create the rule_runs document."""
    if mode not in MODES:
        raise RangeError(f"mode must be one of {MODES}")
    sc = db.scenarios.find_one({"scenario_id": scenario_id})
    if sc is None or sc["status"] not in ("approved", "completed"):
        raise ScenarioStateError(f"scenario is {sc['status'] if sc else 'missing'}; only approved or completed "
                                 "scenarios can run")
    meta = db.pipeline_meta.find_one({"_id": "meta"})
    if meta is None:
        raise RangeError("no data loaded yet; run the pipeline first")
    w = sc["spec"]["params"]["window_hours"]
    if mode == "all":
        start, end = None, None
    elif mode == "new":
        start, end = sc.get("covered_until") or meta["data_origin"], None
    rs, re_ = aligned_range(meta["data_origin"], meta["slice_end"], w, start, end)
    res = db.scenarios.find_one_and_update({"scenario_id": scenario_id, "status": sc["status"]},
                                           {"$set": {"status": "running"}})
    if res is None:
        raise ScenarioStateError("scenario changed state concurrently")
    run_id = uuid.uuid4().hex
    db.rule_runs.insert_one({"run_id": run_id, "scenario_id": scenario_id, "status": "running", "mode": mode,
                             "range_start": rs, "range_end": re_, "started_at": _now(), "finished_at": None,
                             "error": None, "metrics": None})
    return run_id


def _blocks_in_range(db, rs: datetime, re_: datetime, full: bool) -> list[dict]:
    out = []
    for b in db.stg_pattern_blocks.find({}, {"_id": 0, "pattern_type": 1, "tx_ids": 1, "first_ts": 1, "last_ts": 1}):
        if b.get("first_ts") and b.get("last_ts"):
            if rs <= b["first_ts"] and b["last_ts"] < re_:
                out.append(b)
        elif full:                     # blocks without timestamps (older loads) count only for full-data runs
            out.append(b)
    return out


def execute_run(db, scenario_id: str, run_id: str, max_alerts: Optional[int] = None) -> dict:
    """Never raises for rule errors: writes failed + error to rule_runs and the scenario."""
    s = get_settings()
    max_alerts = max_alerts or s.max_alerts
    t0 = time.time()
    run = db.rule_runs.find_one({"run_id": run_id})
    try:
        sc = db.scenarios.find_one({"scenario_id": scenario_id})
        spec = ScenarioSpec.model_validate(sc["spec"])
        meta = db.pipeline_meta.find_one({"_id": "meta"})
        origin, rs, re_ = meta["data_origin"], run["range_start"], run["range_end"]
        p = spec.params
        pipeline = build_pipeline(spec.direction, p, origin, re_, start=rs)

        rows = []
        for row in db.stg_transactions.aggregate(pipeline, allowDiskUse=True, batchSize=1000):
            rows.append(row)
            if len(rows) > max_alerts:
                raise TooManyAlerts(f"more than {max_alerts} alerts; tighten the numbers "
                                    "(raise min_counterparties or shorten window_hours)")

        laundering = {d["tx_id"] for d in db.stg_labels.find({}, {"tx_id": 1, "_id": 0})}
        blocks = _blocks_in_range(db, rs, re_, full=run.get("mode", "all") == "all")
        cand = []
        for r in rows:
            ws = origin + timedelta(hours=r["bucket"] * p.window_hours)
            cand.append((make_alert_id(scenario_id, r["account_id"], spec.direction, ws), ws, r))
        existing = {a["alert_id"] for a in db.alerts.find({"alert_id": {"$in": [c[0] for c in cand]}}, {"alert_id": 1})}
        alerts, truths, full_lists = [], [], []
        created = _now()
        for aid, ws, r in cand:
            full_tx = sorted(r["tx_ids"])
            full_lists.append(full_tx)                    # metrics cover every alert in the range, old or new
            if aid in existing:
                continue
            alerts.append({
                "alert_id": aid, "scenario_id": scenario_id, "run_id": run_id, "direction": spec.direction,
                "account_id": r["account_id"], "bucket": r["bucket"], "window_hours": p.window_hours,
                "window_start": ws, "window_end": ws + timedelta(hours=p.window_hours),
                "distinct_counterparties": r["distinct_counterparties"], "tx_count": r["tx_count"],
                "tx_ids": full_tx[:MAX_STORED_TX_IDS], "tx_ids_truncated": len(full_tx) > MAX_STORED_TX_IDS,
                "first_ts": r["first_ts"], "last_ts": r["last_ts"], "status": "new", "created_at": created})
            truths.append({"alert_id": aid, "scenario_id": scenario_id, **alert_truth(full_tx, laundering)})
        for i in range(0, len(alerts), INSERT_BATCH):
            db.alerts.insert_many(alerts[i:i + INSERT_BATCH], ordered=False)
            db.alert_truth.insert_many(truths[i:i + INSERT_BATCH], ordered=False)   # truth never on alerts

        metrics = compute_metrics(spec.direction, full_lists, laundering, blocks, meta["slice_hours"], time.time() - t0)
        metrics.update({"new_alerts": len(alerts), "existing_alerts": len(existing),
                        "range_hours": round((re_ - rs).total_seconds() / 3600, 2)})
        db.rule_runs.update_one({"run_id": run_id}, {"$set": {"status": "completed", "metrics": metrics,
                                                              "finished_at": _now()}})
        covered = max(sc.get("covered_until") or re_, re_)
        db.scenarios.update_one({"scenario_id": scenario_id}, {"$set": {"status": "completed", "covered_until": covered}})
        log.info("rule_run_completed", scenario_id=scenario_id, run_id=run_id, alerts=len(alerts),
                 duration_ms=int((time.time() - t0) * 1000))
        return metrics
    except Exception as e:
        code = "too_many_alerts" if isinstance(e, TooManyAlerts) else "rule_run_failed"
        err = {"code": code, "message": str(e)}
        db.rule_runs.update_one({"run_id": run_id}, {"$set": {"status": "failed", "error": err,
                                                              "finished_at": _now()}})
        # a failed first run fails the scenario (clone to change numbers); a failed later run keeps it usable
        had_success = db.rule_runs.count_documents({"scenario_id": scenario_id, "status": "completed"}) > 0
        db.scenarios.update_one({"scenario_id": scenario_id},
                                {"$set": {"status": "completed" if had_success else "failed"}})
        log.warning("rule_run_failed", scenario_id=scenario_id, run_id=run_id, error=code)
        return {"error": err}


def run_scenario(db, scenario_id: str, max_alerts: Optional[int] = None, mode: str = "all",
                 start: Optional[datetime] = None, end: Optional[datetime] = None) -> dict:
    return execute_run(db, scenario_id, start_run(db, scenario_id, mode, start, end), max_alerts)

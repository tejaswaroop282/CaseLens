"""Shared API helpers: database dependency, JSON-safe conversion, background job runner."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Callable

from app.db import get_db
from app.logging import get_logger

log = get_logger("jobs")
_job_lock = threading.Lock()          # one background job at a time per process (docs/04 section 3)


def database():
    """FastAPI dependency; tests override it with a throwaway database."""
    return get_db()


def jsonable(v: Any) -> Any:
    if isinstance(v, datetime):
        v = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items() if k != "_id"}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return v


def run_job(name: str, fn: Callable, *args) -> None:
    """Background job wrapper: serialised, never raises (each job writes its own status and error)."""
    with _job_lock:
        try:
            fn(*args)
        except Exception as e:
            log.error("background_job_crashed", job=name, error=type(e).__name__)


def recover_interrupted(db) -> dict:
    """On startup: anything left running by a crash becomes failed/interrupted."""
    err = {"code": "interrupted", "message": "the server stopped while this was running"}
    now = datetime.now(timezone.utc)
    runs = db.rule_runs.update_many({"status": "running"}, {"$set": {"status": "failed", "error": err,
                                                                    "finished_at": now}})
    scen = db.scenarios.update_many({"status": "running"}, {"$set": {"status": "failed"}})
    cases = db.cases.update_many({"status": {"$in": ["queued", "running"]}},
                                 {"$set": {"status": "failed", "error": err, "finished_at": now}})
    return {"rule_runs": runs.modified_count, "scenarios": scen.modified_count, "cases": cases.modified_count}

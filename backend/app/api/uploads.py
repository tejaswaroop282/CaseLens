"""M7 / D17 upload endpoints: upload -> validate (background) -> append (background) -> run scenarios on new data."""
from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile

from app.auth import User, current_user, require_owner

from app.api.common import database, jsonable, run_job
from app.config import get_settings
from app.errors import InvalidState, NotFound, ValidationFailed
from app.logging import get_logger
from pipeline import upload as up

log = get_logger("api.uploads")
router = APIRouter(prefix="/uploads", tags=["uploads"])
CHUNK = 1 << 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _save(src: UploadFile, dest, max_bytes: int) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with open(dest, "wb") as f:
        while chunk := src.file.read(CHUNK):
            size += len(chunk)
            if size > max_bytes:
                f.close(); dest.unlink(missing_ok=True)
                raise ValidationFailed(f"file is larger than {max_bytes // (1 << 20)} MB", code="file_too_large")
            f.write(chunk)
    return size


def _validate_job(db, upload_id: str) -> None:
    try:
        rep = up.validate(db, up.uploads_dir() / upload_id / "transactions.csv")
        status = "validated" if rep.get("ok") else "invalid"
        db.uploads.update_one({"upload_id": upload_id}, {"$set": {"status": status, "report": rep, "validated_at": _now()}})
    except Exception as e:
        db.uploads.update_one({"upload_id": upload_id}, {"$set": {"status": "invalid",
                              "report": {"ok": False, "error": f"{type(e).__name__}: {e}"}}})
        log.warning("upload_validate_failed", upload_id=upload_id, error=type(e).__name__)


def _append_job(db, upload_id: str) -> None:
    s = get_settings()
    folder = up.uploads_dir() / upload_id
    u = db.uploads.find_one({"upload_id": upload_id})
    run = {"run_id": uuid.uuid4().hex, "step": "upload", "started_at": _now(), "config_hash": u["sha256"]}
    try:
        s3_key = None
        try:
            s3_key = up.raw_copy(folder / "transactions.csv", u["sha256"])
        except Exception as e:                       # raw copy is best effort; the append itself must not depend on AWS
            log.warning("upload_s3_copy_failed", upload_id=upload_id, error=type(e).__name__)
        seq = db.uploads.count_documents({"status": "appended"}) + 1
        counts = up.append(db, folder / "transactions.csv", upload_id, seq)
        if u.get("has_patterns"):
            counts["relabel"] = up.relabel_from_patterns(db, folder / "patterns.txt")
        db.uploads.update_one({"upload_id": upload_id}, {"$set": {"status": "appended", "result": counts,
                                                                  "s3_key": s3_key, "appended_at": _now()}})
        db.pipeline_runs.insert_one({**run, "status": "ok", "finished_at": _now(), "row_counts": counts,
                                     "notes": [f"upload {u['filename']} ({upload_id})"]})
        if s3_key and not s.keep_local_raw:
            shutil.rmtree(folder, ignore_errors=True)   # S3 keeps the original
    except Exception as e:
        db.uploads.update_one({"upload_id": upload_id}, {"$set": {"status": "failed", "error": f"{type(e).__name__}: {e}"}})
        db.pipeline_runs.insert_one({**run, "status": "failed", "finished_at": _now(), "error": str(e)})
        log.warning("upload_append_failed", upload_id=upload_id, error=type(e).__name__)


@router.post("", status_code=202)
def create(background: BackgroundTasks, file: UploadFile = File(...), patterns: Optional[UploadFile] = File(None),
           db=Depends(database), user: User = Depends(require_owner)):
    if db.pipeline_meta.find_one({"_id": "meta"}) is None:
        raise InvalidState("load the base data first (python -m pipeline.run --step all)", code="data_not_loaded")
    name = (file.filename or "upload.csv")
    if not name.lower().endswith(".csv"):
        raise ValidationFailed("upload a .csv file in the IBM transaction format", code="bad_file_type")
    upload_id = uuid.uuid4().hex
    folder = up.uploads_dir() / upload_id
    max_bytes = get_settings().max_upload_mb << 20
    size = _save(file, folder / "transactions.csv", max_bytes)
    has_patterns = bool(patterns and patterns.filename)
    if has_patterns:
        _save(patterns, folder / "patterns.txt", max_bytes)
    doc = {"upload_id": upload_id, "filename": name, "bytes": size, "sha256": up.sha256_file(folder / "transactions.csv"),
           "has_patterns": has_patterns, "patterns_filename": patterns.filename if has_patterns else None,
           "status": "validating", "report": None, "result": None, "created_at": _now()}
    db.uploads.insert_one(dict(doc))
    background.add_task(run_job, "upload_validate", _validate_job, db, upload_id)
    return jsonable(doc)


@router.get("")
def list_(db=Depends(database), user: User = Depends(current_user)):
    return jsonable({"items": list(db.uploads.find({}, {"_id": 0}).sort("created_at", -1).limit(50))})


@router.get("/{upload_id}")
def get(upload_id: str, db=Depends(database), user: User = Depends(current_user)):
    u = db.uploads.find_one({"upload_id": upload_id}, {"_id": 0})
    if u is None:
        raise NotFound(f"upload {upload_id} not found")
    return jsonable(u)


@router.post("/{upload_id}/append", status_code=202)
def append(upload_id: str, background: BackgroundTasks, db=Depends(database), user: User = Depends(require_owner)):
    res = db.uploads.find_one_and_update({"upload_id": upload_id, "status": "validated"},
                                         {"$set": {"status": "appending"}})
    if res is None:
        u = db.uploads.find_one({"upload_id": upload_id})
        if u is None:
            raise NotFound(f"upload {upload_id} not found")
        raise InvalidState(f"upload is {u['status']}; only a validated upload can be appended")
    background.add_task(run_job, "upload_append", _append_job, db, upload_id)
    return {"upload_id": upload_id, "status": "appending"}

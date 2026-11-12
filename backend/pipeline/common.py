"""Shared helpers for pipeline steps: paths, checksums, config hash, run records."""
from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import REPO_ROOT, get_settings
from app.logging import get_logger

log = get_logger("pipeline")

DATASET = "HI-Small"
TRANS_FILE = "HI-Small_Trans.csv"
PATTERNS_FILE = "HI-Small_Patterns.txt"
RAW_FILES = (TRANS_FILE, PATTERNS_FILE)
S3_IBM_PREFIX = "raw/ibm_aml/"
S3_DOCS_PREFIX = "raw/reg_docs/"
TS_FORMAT = "%Y/%m/%d %H:%M"

# The CSV has two columns both named "Account": always read with explicit names (pitfall 1).
COLS = ["ts_raw", "from_bank", "from_account", "to_bank", "to_account", "amount_received", "currency_received",
        "amount_paid", "currency_paid", "payment_format", "is_laundering"]
KEY_COLS = COLS[:10]          # the row key uses every column except the label


def ibm_dir() -> Path:
    return get_settings().data_dir / "ibm"


def label_rows_path() -> Path:
    return get_settings().data_dir / "label_rows.jsonl"


def sources_yaml() -> Path:
    return REPO_ROOT / "docs" / "SOURCES.yaml"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def row_key(values: list[str]) -> str:
    """sha1 over the ten raw (whitespace-stripped) non-label fields, joined with '|'."""
    return hashlib.sha1("|".join(values).encode("utf-8")).hexdigest()


def config_hash(checksums: dict[str, str], extra: Optional[dict] = None) -> str:
    s = get_settings()
    payload = {"checksums": dict(sorted(checksums.items())), "slice_hours": s.slice_hours,
               "max_rows": s.max_rows, "id_pattern": s.id_pattern, **(extra or {})}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


@dataclass
class RunRecord:
    step: str
    config_hash: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: datetime = field(default_factory=utcnow)
    row_counts: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def note(self, msg: str) -> None:
        self.notes.append(msg)
        log.info("pipeline_note", step=self.step, note=msg)


def last_ok_run(db, step: str) -> Optional[dict]:
    return db.pipeline_runs.find_one({"step": step, "status": "ok"}, sort=[("finished_at", -1)])


def should_skip(db, step: str, chash: str, force: bool) -> bool:
    prev = last_ok_run(db, step)
    if not force and prev and prev.get("config_hash") == chash:
        log.info("pipeline_step_skipped", step=step, reason="config_hash unchanged", config_hash=chash)
        return True
    return False


@contextmanager
def recorded_run(db, step: str, chash: str):
    """Yields a RunRecord; appends one pipeline_runs document with status ok or failed."""
    rec = RunRecord(step=step, config_hash=chash)
    log.info("pipeline_step_start", step=step, run_id=rec.run_id)
    status, error = "ok", None
    try:
        yield rec
    except BaseException as e:
        status, error = "failed", f"{type(e).__name__}: {e}"
        raise
    finally:
        doc = {"run_id": rec.run_id, "step": step, "status": status, "config_hash": chash,
               "started_at": rec.started_at, "finished_at": utcnow(), "row_counts": rec.row_counts,
               "notes": rec.notes, "error": error, **rec.extra}
        db.pipeline_runs.insert_one(doc)
        log.info("pipeline_step_end", step=step, status=status, row_counts=rec.row_counts)


def mongo_size_gb(db) -> float:
    st = db.command("dbStats")
    return (st.get("storageSize", 0) + st.get("indexSize", 0)) / 1024 ** 3


def raw_checksums(db) -> dict[str, str]:
    """Checksums recorded by the last successful raw step."""
    prev = last_ok_run(db, "raw")
    if not prev:
        raise RuntimeError("run the raw step first: python -m pipeline.run --step raw")
    return prev["checksums"]

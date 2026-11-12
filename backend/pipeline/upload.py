"""M7 / D17: upload new transaction files in the IBM format and append them to staging.

Two steps: validate (report only, nothing saved) and append. Rows already loaded are skipped with multiset
logic on row_key: if a key exists k times in staging, its first k occurrences in the upload are skipped, so
re-uploading a file adds nothing while genuine duplicate transactions inside a new file are kept.
Laundering labels (if the file has them) go only to the evaluation-only collections."""
from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from app.config import get_settings
from pipeline.common import COLS, log, mongo_size_gb, sha256_file
from pipeline.stage import read_chunks, transform_chunk

FAR_FUTURE = datetime(9999, 1, 1, tzinfo=timezone.utc)
SIZE_CHECK_EVERY = 200_000
MAX_EXAMPLES = 20


def uploads_dir() -> Path:
    return get_settings().data_dir / "uploads"


def check_header(path: Path) -> Optional[str]:
    """None if the file looks like an IBM transaction CSV, else a reason."""
    with open(path, encoding="utf-8", newline="") as f:
        header = next(csv.reader(f), None)
    if not header:
        return "the file is empty"
    if len(header) != len(COLS):
        return f"expected {len(COLS)} columns (IBM transaction format), found {len(header)}"
    return None


def existing_counts(db, keys: set[str]) -> Counter:
    out: Counter = Counter()
    ks = list(keys)
    for i in range(0, len(ks), 5000):
        for r in db.stg_transactions.aggregate([{"$match": {"row_key": {"$in": ks[i:i + 5000]}}},
                                                {"$group": {"_id": "$row_key", "n": {"$sum": 1}}}]):
            out[r["_id"]] = r["n"]
    return out


def _iter(db, path: Path, meta: dict, tx_prefix: str):
    """Yield (chunk result, docs before origin) per chunk, using the same cleaning as staging."""
    origin = meta["data_origin"]
    bank_account = meta.get("account_key") == "bank_account"
    start = 0
    for ch in read_chunks(path):
        res = transform_chunk(ch, start, FAR_FUTURE, bank_account, dataset=tx_prefix)
        start += len(ch)
        before = [d for d in res.docs if d["ts"] < origin]
        if before:
            res.docs = [d for d in res.docs if d["ts"] >= origin]
        yield res, before


def validate(db, path: Path) -> dict:
    meta = db.pipeline_meta.find_one({"_id": "meta"})
    if meta is None:
        return {"ok": False, "error": "load the base data first (python -m pipeline.run --step all)"}
    if (why := check_header(path)):
        return {"ok": False, "error": why}
    rep = {"rows": 0, "valid": 0, "rejected": 0, "reasons": Counter(), "examples": [], "ts_min": None,
           "ts_max": None, "labeled_rows": 0, "keys": Counter()}
    for res, before in _iter(db, path, meta, "VALIDATE"):
        rep["rows"] += res.in_slice
        for tx, why in res.rejects + [(d["tx_id"], "before_data_origin") for d in before]:
            rep["rejected"] += 1; rep["reasons"][why] += 1
            if len(rep["examples"]) < MAX_EXAMPLES:
                rep["examples"].append({"row": int(tx.rsplit("-", 1)[1]) + 2, "reason": why})   # +2: header, 1-based
        rep["valid"] += len(res.docs)
        before_ids = {d["tx_id"] for d in before}
        rep["labeled_rows"] += sum(1 for r in res.label_rows if r["tx_id"] not in before_ids)
        for d in res.docs:
            rep["keys"][d["row_key"]] += 1
            rep["ts_min"] = d["ts"] if rep["ts_min"] is None or d["ts"] < rep["ts_min"] else rep["ts_min"]
            rep["ts_max"] = d["ts"] if rep["ts_max"] is None or d["ts"] > rep["ts_max"] else rep["ts_max"]
    have = existing_counts(db, set(rep["keys"]))
    dup = sum(min(n, have.get(k, 0)) for k, n in rep["keys"].items())
    keys = rep.pop("keys")
    rep.update({"ok": rep["valid"] > 0 and rep["valid"] > dup, "already_loaded": dup, "to_append": rep["valid"] - dup,
                "reasons": dict(rep["reasons"]), "distinct_keys": len(keys),
                "current_data_end": meta["slice_end"]})
    if rep["valid"] == 0:
        rep["error"] = "no valid rows"
    elif rep["to_append"] == 0:
        rep["error"] = "every row is already loaded"
    return rep


def new_data_end(meta: dict, ts_max: datetime) -> datetime:
    """Exclusive end of loaded data, rounded up to the next full hour after the newest transaction."""
    nxt = ts_max.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return max(meta["slice_end"], nxt)


def append(db, path: Path, upload_id: str, seq: int) -> dict:
    """Append new rows. Returns counts. Raises on the MongoDB size guard (rows inserted so far stay)."""
    s = get_settings()
    meta = db.pipeline_meta.find_one({"_id": "meta"})
    prefix = f"UP{seq:03d}"
    remaining: Optional[Counter] = None
    counts = {"rows": 0, "appended": 0, "already_loaded": 0, "rejected": 0, "labels_added": 0}
    ts_max = None
    next_check = SIZE_CHECK_EVERY
    for res, before in _iter(db, path, meta, prefix):
        counts["rows"] += res.in_slice
        counts["rejected"] += len(res.rejects) + len(before)
        if remaining is None:
            remaining = Counter()
        chunk_keys = {d["row_key"] for d in res.docs} - set(remaining)
        remaining.update(existing_counts(db, chunk_keys))          # first sighting of a key: how many exist
        for k in chunk_keys:
            remaining.setdefault(k, 0)
        new_docs = []
        for d in res.docs:
            if remaining[d["row_key"]] > 0:
                remaining[d["row_key"]] -= 1; counts["already_loaded"] += 1
            else:
                new_docs.append({**d, "upload_id": upload_id})
        if new_docs:
            db.stg_transactions.insert_many(new_docs, ordered=False)
            counts["appended"] += len(new_docs)
            mx = max(d["ts"] for d in new_docs)
            ts_max = mx if ts_max is None or mx > ts_max else ts_max
            new_ids = {d["tx_id"] for d in new_docs}
            labels = [{"tx_id": r["tx_id"], "is_laundering": True, "pattern_type": "other", "pattern_id": None}
                      for r in res.label_rows if r["tx_id"] in new_ids]
            if labels:
                db.stg_labels.insert_many(labels, ordered=False)       # evaluation-only collection
                counts["labels_added"] += len(labels)
        if counts["rows"] >= next_check:
            next_check += SIZE_CHECK_EVERY
            if (gb := mongo_size_gb(db)) > s.mongo_max_gb:
                raise RuntimeError(f"MongoDB is {gb:.2f} GB > MONGO_MAX_GB={s.mongo_max_gb}; upload stopped")
    if ts_max is not None:
        end = new_data_end(meta, ts_max)
        db.pipeline_meta.update_one({"_id": "meta"}, {
            "$set": {"slice_end": end, "slice_hours": int((end - meta["data_origin"]).total_seconds() // 3600)},
            "$push": {"uploads": {"upload_id": upload_id, "appended": counts["appended"], "data_end": end}}})
        counts["data_end"] = end
    log.info("upload_appended", upload_id=upload_id, **{k: v for k, v in counts.items() if k != "data_end"})
    return counts


def relabel_from_patterns(db, patterns_path: Path) -> dict:
    """Optional: rebuild fan pattern blocks over ALL loaded data with an uploaded patterns file."""
    from pipeline.labels import build_labels
    from pipeline.patterns import parse_file
    meta = db.pipeline_meta.find_one({"_id": "meta"})
    labeled = [d["tx_id"] for d in db.stg_labels.find({}, {"tx_id": 1})]
    key_to_tx: dict[str, list[str]] = {}
    for i in range(0, len(labeled), 5000):
        for t in db.stg_transactions.find({"tx_id": {"$in": labeled[i:i + 5000]}}, {"tx_id": 1, "row_key": 1}):
            key_to_tx.setdefault(t["row_key"], []).append(t["tx_id"])
    res = build_labels(parse_file(patterns_path), key_to_tx, meta["slice_end"])
    db.stg_labels.drop(); db.stg_pattern_blocks.drop()
    if res.labels:
        db.stg_labels.insert_many(res.labels, ordered=False)
    if res.blocks:
        db.stg_pattern_blocks.insert_many(res.blocks, ordered=False)
    db.stg_labels.create_index("tx_id", unique=True)
    db.stg_pattern_blocks.create_index("pattern_id", unique=True)
    db.stg_pattern_blocks.create_index("pattern_type")
    return res.counts


def raw_copy(path: Path, digest: str) -> Optional[str]:
    """Keep the original file unchanged in S3 (raw layer) when a bucket is configured."""
    if not get_settings().s3_bucket:
        return None
    from pipeline import s3io
    key = f"raw/uploads/{digest}.csv"
    s3io.upload_if_needed(path, key)
    return key


__all__ = ["validate", "append", "relabel_from_patterns", "raw_copy", "uploads_dir", "sha256_file"]

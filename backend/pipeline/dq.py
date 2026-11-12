"""Data-quality checks per layer. One dq_reports document per run; any failed check -> non-zero exit."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from app.config import get_settings
from pipeline.common import (RAW_FILES, S3_IBM_PREFIX, last_ok_run, log, mongo_size_gb, utcnow)
from pipeline.patterns import FAN_TYPES

LABEL_KEYS = ("is_laundering", "pattern_type", "pattern_id", "is_suspicious", "n_laundering_tx")
REQUIRED_FIELDS = ("tx_id", "ts", "from_account", "to_account", "amount_paid", "currency_paid",
                   "amount_received", "currency_received", "payment_format")


@dataclass
class Check:
    layer: str
    name: str
    status: str          # pass | warn | fail | skip
    value: Any = None
    expected: Any = None
    detail: str = ""


def _eq(layer, name, value, expected, detail="") -> Check:
    return Check(layer, name, "pass" if value == expected else "fail", value, expected, detail)


def dir_size_gb(path: Path) -> float:
    if not path.exists():
        return 0.0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1024 ** 3


# ---------------- layers ----------------
def check_raw(db) -> list[Check]:
    run = last_ok_run(db, "raw")
    if not run:
        return [Check("raw", "raw step ran", "fail", None, "ok run in pipeline_runs")]
    if not get_settings().s3_bucket:
        return [Check("raw", "s3 checksum", "skip", detail="S3_BUCKET not set")]
    from pipeline import s3io
    out = []
    for name in RAW_FILES:
        remote = s3io.head_sha256(S3_IBM_PREFIX + name)
        out.append(_eq("raw", f"s3 checksum {name}", remote, run["checksums"].get(name),
                       "S3 object metadata vs checksum recorded by the raw step"))
    return out


def check_staging(db) -> list[Check]:
    run = last_ok_run(db, "staging")
    meta = db.pipeline_meta.find_one({"_id": "meta"})
    if not run or not meta:
        return [Check("staging", "staging step ran", "fail", None, "ok run and pipeline_meta")]
    c = run["row_counts"]
    coll = db.stg_transactions
    out = [_eq("staging", "written + rejected == in_slice", c["written"] + c["rejected"], c["in_slice"])]
    share = c["rejected"] / c["in_slice"] if c["in_slice"] else 0.0
    out.append(Check("staging", "rejected share", "pass" if share <= 0.001 else "fail", round(share, 6), "<= 0.001"))
    out.append(_eq("staging", "documents == written", coll.estimated_document_count(), c["written"]))
    nulls = coll.count_documents({"$or": [{f: {"$in": [None, ""]}} for f in REQUIRED_FIELDS]})
    out.append(_eq("staging", "nulls in required fields", nulls, 0))
    dup = list(coll.aggregate([{"$group": {"_id": "$tx_id", "n": {"$sum": 1}}}, {"$match": {"n": {"$gt": 1}}},
                               {"$count": "dups"}], allowDiskUse=True))
    out.append(_eq("staging", "duplicate tx_id", dup[0]["dups"] if dup else 0, 0))
    rng = list(coll.aggregate([{"$group": {"_id": None, "lo": {"$min": "$ts"}, "hi": {"$max": "$ts"}}}]))
    if rng:
        lo, hi = rng[0]["lo"], rng[0]["hi"]
        ok = meta["data_origin"] <= lo and hi < meta["slice_end"]
        out.append(Check("staging", "timestamp range", "pass" if ok else "fail", f"{lo} .. {hi}",
                         f"[{meta['data_origin']}, {meta['slice_end']})"))
    leaked = coll.count_documents({"$or": [{k: {"$exists": True}} for k in LABEL_KEYS]})
    out.append(_eq("staging", "stg_transactions has no label field", leaked, 0))
    return out


def check_labels(db) -> list[Check]:
    run = last_ok_run(db, "labels")
    st = last_ok_run(db, "staging")
    if not run or not st:
        return [Check("labels", "labels step ran", "fail", None, "ok run in pipeline_runs")]
    c = run["row_counts"]
    written = st["row_counts"]["written"] or 1
    share = db.stg_labels.estimated_document_count() / written
    far = not (0.0002 <= share <= 0.005)
    out = [Check("labels", "laundering share in slice", "warn" if far else "pass", round(share, 6),
                 "about 0.001", "report only")]
    for t in FAN_TYPES:
        n = db.stg_pattern_blocks.count_documents({"pattern_type": t})
        out.append(Check("labels", f"complete {t} blocks in slice", "pass" if n >= 10 else "warn", n, ">= 10",
                         "" if n >= 10 else "raise SLICE_HOURS (see slice_advice)"))
    in_slice = c.get("lines_in_slice", 0)
    um = c.get("lines_unmatched", 0) / in_slice if in_slice else 0.0
    out.append(Check("labels", "unmatched pattern lines", "pass" if um <= 0.05 else "fail", round(um, 4), "<= 0.05"))
    return out


def check_docs(db) -> list[Check]:
    run = last_ok_run(db, "docs")
    if not run:
        return [Check("docs", "docs step ran", "skip", detail="no docs run yet (PDFs not chosen)")]
    s = get_settings()
    from pipeline.ingest_docs import get_store
    store = get_store(embeddings=_NoEmbed())
    got = store.get(include=["metadatas"])
    metas = got.get("metadatas") or []
    out = []
    for doc_id in run.get("chunks_per_doc", {}):
        n = sum(1 for m in metas if m and m.get("doc_id") == doc_id)
        out.append(Check("docs", f"chunks for {doc_id}", "pass" if n >= 1 else "fail", n, ">= 1"))
    keys = ("doc_id", "title", "source_url", "page", "chunk_id")
    bad = sum(1 for m in metas if not m or any(m.get(k) in (None, "") for k in keys))
    out.append(_eq("docs", "chunks with missing metadata", bad, 0))
    est = run["row_counts"].get("estimated_tokens", 0)
    out.append(Check("docs", "estimated embedding tokens", "pass" if est <= s.embed_token_budget else "fail",
                     est, f"<= {s.embed_token_budget}"))
    return out


def check_disk(db) -> list[Check]:
    s = get_settings()
    gb = mongo_size_gb(db)
    status = "fail" if gb > s.mongo_max_gb else ("warn" if gb > 0.7 * s.mongo_max_gb else "pass")
    out = [Check("disk", "mongo storageSize + indexSize (GB)", status, round(gb, 3), f"< {s.mongo_max_gb}")]
    d = dir_size_gb(s.data_dir)
    if not s.keep_local_raw:
        out.append(Check("disk", "data/ size (GB)", "pass" if d < 1 else "warn", round(d, 3), "< 1"))
    return out


from langchain_core.embeddings import Embeddings  # noqa: E402


class _NoEmbed(Embeddings):
    """Reading Chroma metadata needs no embeddings; this guarantees no paid call is made."""
    def embed_documents(self, texts): raise RuntimeError("dq must not embed")
    def embed_query(self, text): raise RuntimeError("dq must not embed")


LAYERS = {"raw": check_raw, "staging": check_staging, "labels": check_labels, "docs": check_docs,
          "disk": check_disk}


def run_dq(db, layers: Optional[list[str]] = None) -> tuple[bool, list[Check]]:
    run_id = uuid.uuid4().hex
    checks: list[Check] = []
    for name in layers or list(LAYERS):
        try:
            checks += LAYERS[name](db)
        except Exception as e:
            checks.append(Check(name, "layer check crashed", "fail", detail=f"{type(e).__name__}: {e}"))
    for layer in sorted({c.layer for c in checks}):
        db.dq_reports.insert_one({"run_id": run_id, "layer": layer, "ts": utcnow(),
                                  "checks": [asdict(c) for c in checks if c.layer == layer]})
    for c in checks:
        print(f"[{c.status.upper():4}] {c.layer:8} {c.name}: {c.value} (expected {c.expected}) {c.detail}")
    failed = [c for c in checks if c.status == "fail"]
    log.info("dq_done", run_id=run_id, checks=len(checks), failed=len(failed))
    return not failed, checks

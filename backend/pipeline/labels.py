"""Labels: evaluation-only collections stg_labels and stg_pattern_blocks.

Only evaluation code, rules/metrics.py and GET /scenarios/{id}/examples may read these collections."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import get_settings
from pipeline.common import (PATTERNS_FILE, S3_IBM_PREFIX, TRANS_FILE, config_hash, ibm_dir, label_rows_path,
                             last_ok_run, raw_checksums, recorded_run, should_skip)
from pipeline.patterns import FAN_TYPES, PatternBlock


@dataclass
class LabelBuild:
    labels: list = field(default_factory=list)          # stg_labels documents
    blocks: list = field(default_factory=list)          # stg_pattern_blocks documents (fan, fully in slice)
    counts: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)


def load_label_rows(path: Path) -> dict[str, list[str]]:
    """row_key -> tx_ids (duplicates in the transaction file are possible: attach all)."""
    out: dict[str, list[str]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            out.setdefault(r["row_key"], []).append(r["tx_id"])
    return out


def build_labels(blocks: list[PatternBlock], key_to_tx: dict[str, list[str]], slice_end: datetime) -> LabelBuild:
    """Pure function. A pattern line is out of slice if its timestamp is at or after slice_end; an in-slice
    line must match an in-slice laundering row by row_key, otherwise it is unmatched."""
    b = LabelBuild()
    tx_block: dict[str, PatternBlock] = {}
    c = {"blocks_total": len(blocks), "fan_blocks_total": 0, "fan_blocks_kept": 0, "fan_blocks_out_of_slice": 0,
         "fan_blocks_no_match": 0, "lines_in_slice": 0, "lines_matched": 0, "lines_unmatched": 0,
         "lines_out_of_slice": 0}
    for blk in blocks:
        matched: list[str] = []
        n_out = n_unmatched = 0
        for ln in blk.lines:
            if ln.ts is not None and ln.ts >= slice_end:
                n_out += 1
                continue
            c["lines_in_slice"] += 1
            txs = key_to_tx.get(ln.key)
            if txs:
                c["lines_matched"] += 1
                matched.extend(txs)
            else:
                n_unmatched += 1
        c["lines_unmatched"] += n_unmatched
        c["lines_out_of_slice"] += n_out
        for t in matched:                                  # prefer a fan block if a tx is in several blocks
            prev = tx_block.get(t)
            if prev is None or (prev.pattern_type not in FAN_TYPES and blk.pattern_type in FAN_TYPES):
                tx_block[t] = blk
        if blk.pattern_type in FAN_TYPES:
            c["fan_blocks_total"] += 1
            if n_out:
                c["fan_blocks_out_of_slice"] += 1
            elif not matched:
                c["fan_blocks_no_match"] += 1
            else:
                c["fan_blocks_kept"] += 1
                b.blocks.append({"pattern_id": blk.pattern_id, "pattern_type": blk.pattern_type,
                                 "tx_ids": sorted(set(matched)), "n_lines": len(blk.lines),
                                 "n_matched": len(blk.lines) - n_unmatched, "n_unmatched": n_unmatched})
        if n_unmatched and len(b.notes) < 20:
            b.notes.append(f"{blk.pattern_id} ({blk.pattern_type}): {n_unmatched} unmatched in-slice lines")

    all_tx = sorted({t for txs in key_to_tx.values() for t in txs})
    for t in all_tx:
        blk = tx_block.get(t)
        is_fan = blk is not None and blk.pattern_type in FAN_TYPES
        b.labels.append({"tx_id": t, "is_laundering": True,
                         "pattern_type": blk.pattern_type if is_fan else "other",
                         "pattern_id": blk.pattern_id if blk else None})
    c["label_rows"] = len(all_tx)
    c["fan_blocks_kept_by_type"] = {t: sum(1 for x in b.blocks if x["pattern_type"] == t) for t in FAN_TYPES}
    b.counts = c
    return b


def run_labels(db, force: bool = False) -> Optional[dict]:
    from pipeline import s3io
    from pipeline.patterns import parse_file
    s = get_settings()
    chash = config_hash(raw_checksums(db))
    st = last_ok_run(db, "staging")
    if not st or st["config_hash"] != chash:
        raise RuntimeError("staging is missing or stale for this configuration; run --step staging first")
    if should_skip(db, "labels", chash, force):
        return None
    meta = db.pipeline_meta.find_one({"_id": "meta"})
    pat = s3io.ensure_local(ibm_dir() / PATTERNS_FILE, S3_IBM_PREFIX + PATTERNS_FILE)

    with recorded_run(db, "labels", chash) as rec:
        from pipeline.patterns import parse_file
        blocks = parse_file(pat)
        res = build_labels(blocks, load_label_rows(label_rows_path()), meta["slice_end"])
        db.stg_labels.drop(); db.stg_pattern_blocks.drop()
        if res.labels:
            db.stg_labels.insert_many(res.labels, ordered=False)
        if res.blocks:
            db.stg_pattern_blocks.insert_many(res.blocks, ordered=False)
        db.stg_labels.create_index("tx_id", unique=True)
        db.stg_pattern_blocks.create_index("pattern_id", unique=True)
        db.stg_pattern_blocks.create_index("pattern_type")
        rec.row_counts = res.counts
        for n in res.notes:
            rec.note(n)
        rec.note(f"block types in file: {sorted({b.pattern_type for b in blocks})}")
        if not s.keep_local_raw:                          # staging and labels succeeded; S3 keeps the originals
            for name in (TRANS_FILE, PATTERNS_FILE):
                p = ibm_dir() / name
                if p.exists():
                    p.unlink()
                    rec.note(f"deleted local raw file {name} (KEEP_LOCAL_RAW=false)")
        return res.counts

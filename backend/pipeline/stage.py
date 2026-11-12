"""Staging: HI-Small_Trans.csv -> MongoDB stg_transactions (no label field) + data/label_rows.jsonl."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from app.config import get_settings
from app.db import ensure_indexes
from pipeline.common import (COLS, DATASET, KEY_COLS, S3_IBM_PREFIX, TRANS_FILE, TS_FORMAT, config_hash,
                             ibm_dir, label_rows_path, mongo_size_gb, raw_checksums, recorded_run,
                             row_key, should_skip)

CHUNK = 100_000
SIZE_CHECK_EVERY = 500_000
REQUIRED = ["from_bank", "from_account", "to_bank", "to_account", "currency_paid", "currency_received",
            "payment_format"]
DOC_FIELDS = ["tx_id", "ts", "from_bank", "from_account", "to_bank", "to_account", "amount_paid", "currency_paid",
              "amount_received", "currency_received", "payment_format", "row_key"]
# row_key = sha1 of the ten raw non-label fields: lets uploads skip rows that are already loaded (D17).


def read_chunks(path: Path, usecols=None, max_rows: Optional[int] = None, chunksize: int = CHUNK):
    """The file has two columns named 'Account': read with explicit names and header=0 (pitfall 1)."""
    return pd.read_csv(path, header=0, names=COLS, usecols=usecols, dtype=str, chunksize=chunksize,
                       nrows=max_rows, keep_default_na=False)


def parse_ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.str.strip(), format=TS_FORMAT, errors="coerce", utc=True)


# ---------------- pass 1 ----------------
@dataclass
class ScanResult:
    rows: int = 0
    earliest: Optional[datetime] = None
    latest: Optional[datetime] = None
    sorted_by_time: bool = True
    bad_ts: int = 0
    accounts: int = 0
    accounts_multi_bank: int = 0
    multi_bank_examples: list = field(default_factory=list)

    @property
    def account_key(self) -> str:
        return "bank_account" if self.accounts_multi_bank else "account"


def scan(path: Path, max_rows: Optional[int] = None, chunksize: int = CHUNK) -> ScanResult:
    r = ScanResult()
    prev_last = None
    pairs = []
    for ch in read_chunks(path, usecols=["ts_raw", "from_bank", "from_account", "to_bank", "to_account"],
                          max_rows=max_rows, chunksize=chunksize):
        r.rows += len(ch)
        ts = parse_ts(ch["ts_raw"])
        r.bad_ts += int(ts.isna().sum())
        good = ts.dropna()
        if len(good):
            lo, hi = good.min(), good.max()
            r.earliest = lo if r.earliest is None else min(r.earliest, lo)
            r.latest = hi if r.latest is None else max(r.latest, hi)
            if not good.is_monotonic_increasing or (prev_last is not None and good.iloc[0] < prev_last):
                r.sorted_by_time = False
            prev_last = good.iloc[-1]
        p = pd.concat([ch[["from_bank", "from_account"]].set_axis(["bank", "account"], axis=1),
                       ch[["to_bank", "to_account"]].set_axis(["bank", "account"], axis=1)])
        pairs.append(p.apply(lambda c: c.str.strip()).drop_duplicates())
        if len(pairs) >= 10:
            pairs = [pd.concat(pairs).drop_duplicates()]
    allp = pd.concat(pairs).drop_duplicates() if pairs else pd.DataFrame(columns=["bank", "account"])
    nb = allp.groupby("account")["bank"].nunique()
    r.accounts = int(len(nb))
    multi = nb[nb > 1]
    r.accounts_multi_bank = int(len(multi))
    r.multi_bank_examples = [
        {"account": a, "banks": sorted(allp.loc[allp["account"] == a, "bank"].tolist())[:5]}
        for a in multi.index[:5]]
    if r.earliest is not None:
        r.earliest, r.latest = r.earliest.to_pydatetime(), r.latest.to_pydatetime()
    return r


def origin_of(earliest: datetime) -> datetime:
    return earliest.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


# ---------------- pass 2 (pure) ----------------
@dataclass
class ChunkResult:
    docs: list
    label_rows: list
    rejects: list           # (tx_id, reason)
    in_slice: int
    past_slice: int         # rows with a valid timestamp at or after slice_end


def transform_chunk(ch: pd.DataFrame, start_index: int, slice_end: datetime, bank_account: bool,
                    dataset: str = DATASET) -> ChunkResult:
    ch = ch.apply(lambda c: c.str.strip())
    n = len(ch)
    tx_ids = pd.Series([f"{dataset}-{i}" for i in range(start_index, start_index + n)], index=ch.index)
    ts = parse_ts(ch["ts_raw"])
    end = pd.Timestamp(slice_end)
    past = ts.notna() & (ts >= end)
    considered = ~past                     # in-slice rows plus rows whose timestamp cannot be parsed
    rejects: list = []

    bad_ts = considered & ts.isna()
    rejects += [(t, "bad_timestamp") for t in tx_ids[bad_ts]]

    paid = pd.to_numeric(ch["amount_paid"], errors="coerce")
    recv = pd.to_numeric(ch["amount_received"], errors="coerce")
    bad_amt = considered & ~bad_ts & ~((paid > 0) & (recv > 0))
    rejects += [(t, "bad_amount") for t in tx_ids[bad_amt]]

    missing = (ch[REQUIRED] == "").any(axis=1)
    bad_req = considered & ~bad_ts & ~bad_amt & missing
    rejects += [(t, "missing_field") for t in tx_ids[bad_req]]

    ok = considered & ~bad_ts & ~bad_amt & ~bad_req
    out = pd.DataFrame({
        "tx_id": tx_ids[ok], "ts": ts[ok],
        "from_bank": ch.loc[ok, "from_bank"], "to_bank": ch.loc[ok, "to_bank"],
        "from_account": ch.loc[ok, "from_account"], "to_account": ch.loc[ok, "to_account"],
        "amount_paid": paid[ok].astype(float), "currency_paid": ch.loc[ok, "currency_paid"],
        "amount_received": recv[ok].astype(float), "currency_received": ch.loc[ok, "currency_received"],
        "payment_format": ch.loc[ok, "payment_format"],
    })
    if bank_account:
        out["from_account"] = out["from_bank"] + "|" + out["from_account"]
        out["to_account"] = out["to_bank"] + "|" + out["to_account"]
    keys = pd.Series([row_key(list(v)) for v in ch.loc[ok, KEY_COLS].itertuples(index=False, name=None)],
                     index=ch.index[ok], dtype=object)
    out["row_key"] = keys
    docs = [{k: (v.to_pydatetime() if k == "ts" else v) for k, v in zip(DOC_FIELDS, row)}
            for row in out[DOC_FIELDS].itertuples(index=False, name=None)]    # label column dropped

    lab = ok & (ch["is_laundering"] == "1")
    label_rows = [{"tx_id": t, "row_key": keys[i]} for i, t in zip(ch.index[lab], tx_ids[lab])]
    return ChunkResult(docs, label_rows, rejects, int(considered.sum()), int(past.sum()))


# ---------------- step ----------------
def run_staging(db, force: bool = False) -> Optional[dict]:
    from pipeline import s3io
    s = get_settings()
    chash = config_hash(raw_checksums(db))
    if should_skip(db, "staging", chash, force):
        return None
    path = s3io.ensure_local(ibm_dir() / TRANS_FILE, S3_IBM_PREFIX + TRANS_FILE)

    with recorded_run(db, "staging", chash) as rec:
        sc = scan(path, s.max_rows)
        if sc.earliest is None:
            raise RuntimeError("no parseable timestamps; check the timestamp format")
        origin = origin_of(sc.earliest)
        slice_end = origin + timedelta(hours=s.slice_hours)
        rec.note(f"pass1: rows={sc.rows} earliest={sc.earliest:%Y-%m-%d %H:%M} latest={sc.latest:%Y-%m-%d %H:%M} "
                 f"sorted_by_time={sc.sorted_by_time} unparseable_ts={sc.bad_ts}")
        rec.note(f"account ids: {sc.accounts} distinct, {sc.accounts_multi_bank} appear under more than one bank "
                 f"-> account_key={sc.account_key}; examples={sc.multi_bank_examples}")
        bank_account = sc.account_key == "bank_account"

        db.stg_transactions.drop()                       # idempotent rebuild
        counts = {"read": 0, "in_slice": 0, "written": 0, "rejected": 0, "past_slice": 0}
        reasons: dict[str, int] = {}
        examples: list = []
        next_check = SIZE_CHECK_EVERY
        lr_path = label_rows_path()
        lr_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lr_path, "w", encoding="utf-8") as lr:
            start = 0
            for ch in read_chunks(path, max_rows=s.max_rows):
                res = transform_chunk(ch, start, slice_end, bank_account)
                start += len(ch)
                counts["read"] += len(ch)
                counts["in_slice"] += res.in_slice
                counts["past_slice"] += res.past_slice
                counts["rejected"] += len(res.rejects)
                for tx, why in res.rejects:
                    reasons[why] = reasons.get(why, 0) + 1
                    if len(examples) < 20:
                        examples.append({"tx_id": tx, "reason": why})
                if res.docs:
                    db.stg_transactions.insert_many(res.docs, ordered=False)
                    counts["written"] += len(res.docs)
                for row in res.label_rows:
                    lr.write(json.dumps(row) + "\n")
                if counts["read"] >= next_check:
                    next_check += SIZE_CHECK_EVERY
                    if (gb := mongo_size_gb(db)) > s.mongo_max_gb:
                        raise RuntimeError(f"MongoDB is {gb:.2f} GB > MONGO_MAX_GB={s.mongo_max_gb}; "
                                           "lower SLICE_HOURS or set MAX_ROWS")
                if sc.sorted_by_time and res.past_slice == len(ch):
                    rec.note(f"file is sorted by time: stopped reading at row {counts['read']}")
                    break
        ensure_indexes(db)
        rec.row_counts = counts
        if reasons:
            rec.note(f"rejects by reason: {reasons}; first examples: {examples}")
        db.pipeline_meta.replace_one({"_id": "meta"}, {
            "_id": "meta", "dataset": DATASET, "data_origin": origin, "slice_hours": s.slice_hours,
            "slice_end": slice_end, "account_key": sc.account_key, "sorted_by_time": sc.sorted_by_time,
            "staging_run_id": rec.run_id, "built_at": datetime.now(timezone.utc)}, upsert=True)
        rec.extra = {"data_origin": origin, "slice_end": slice_end, "account_key": sc.account_key}
        return counts

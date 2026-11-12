"""The single fan rule: one account versus many DISTINCT counterparties in a fixed time bucket.

Buckets count from data_origin with plain arithmetic (decision D5), not rolling windows.
The pandas oracle (tests/oracle.py) defines the expected results."""
from __future__ import annotations

from datetime import datetime

from app.models import ScenarioParams


def keys(direction: str) -> tuple[str, str]:
    if direction == "out":
        return "from_account", "to_account"
    if direction == "in":
        return "to_account", "from_account"
    raise ValueError(f"unsupported direction {direction!r}")


def build_pipeline(direction: str, p: ScenarioParams, origin: datetime, slice_end: datetime,
                   start: datetime | None = None) -> list[dict]:
    """Buckets always count from `origin`; `start`/`slice_end` only limit which transactions are read
    (callers align them to bucket boundaries for date-range runs, D17)."""
    key, other = keys(direction)
    window_ms = p.window_hours * 3600 * 1000
    match: dict = {"ts": {"$gte": start or origin, "$lt": slice_end}}
    if p.payment_formats:
        match["payment_format"] = {"$in": list(p.payment_formats)}
    return [
        {"$match": match},
        {"$addFields": {"bucket": {"$floor": {"$divide": [{"$subtract": ["$ts", origin]}, window_ms]}}}},
        {"$group": {"_id": {"account_id": f"${key}", "bucket": "$bucket"},
                    "counterparties": {"$addToSet": f"${other}"},
                    "tx_count": {"$sum": 1},
                    "tx_ids": {"$push": "$tx_id"},
                    "first_ts": {"$min": "$ts"}, "last_ts": {"$max": "$ts"}}},
        {"$addFields": {"distinct_counterparties": {"$size": "$counterparties"}}},
        {"$match": {"distinct_counterparties": {"$gte": p.min_counterparties}}},
        {"$project": {"_id": 0, "account_id": "$_id.account_id", "bucket": {"$toInt": "$_id.bucket"},
                      "distinct_counterparties": 1, "tx_count": 1, "tx_ids": 1, "first_ts": 1, "last_ts": 1}},
    ]          # run with allowDiskUse=True

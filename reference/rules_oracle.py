"""Pure-pandas reference implementation of the single "fan" rule (direction out or in).
Used in tests as an oracle: the MongoDB aggregation must return the same alerts on a small fixture."""
from __future__ import annotations
import pandas as pd

def bucketize(ts: pd.Series, origin: pd.Timestamp, window_hours: int) -> pd.Series:
    return ((ts - origin) // pd.Timedelta(hours=window_hours)).astype("int64")

def run_rule(df: pd.DataFrame, direction: str, min_counterparties: int, window_hours: int,
             origin: pd.Timestamp) -> pd.DataFrame:
    """df columns: tx_id, ts (datetime64, UTC), from_account, to_account, amount_paid, currency_paid."""
    key, other = ("from_account", "to_account") if direction == "out" else ("to_account", "from_account")
    d = df.assign(bucket=bucketize(df["ts"], origin, window_hours))
    g = d.groupby([key, "bucket"]).agg(
        distinct_counterparties=(other, "nunique"), tx_count=("tx_id", "count"),
        tx_ids=("tx_id", lambda s: sorted(s))).reset_index()
    g = g[g["distinct_counterparties"] >= min_counterparties].rename(columns={key: "account_id"})
    g["window_start"] = origin + g["bucket"] * pd.Timedelta(hours=window_hours)
    g["window_end"] = g["window_start"] + pd.Timedelta(hours=window_hours)
    return g.sort_values(["account_id", "bucket"]).reset_index(drop=True)

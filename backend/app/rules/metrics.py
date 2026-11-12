"""Rule-run metrics. Reads ground truth, so it is evaluation-side code (allowed by docs/02 section 1).

Ground truth: an alert is suspicious if any transaction in it is labeled laundering."""
from __future__ import annotations

from typing import Iterable


def pattern_type_for(direction: str) -> str:
    return {"out": "fan_out", "in": "fan_in"}[direction]


def alert_truth(full_tx_ids: list[str], laundering_tx: set[str]) -> dict:
    n = sum(1 for t in full_tx_ids if t in laundering_tx)
    return {"is_suspicious": n > 0, "n_laundering_tx": n}


def compute_metrics(direction: str, alerts_full_tx: Iterable[list[str]], laundering_tx: set[str],
                    blocks: Iterable[dict], slice_hours: int, duration_seconds: float) -> dict:
    """alerts_full_tx: the FULL tx list of every alert. blocks: stg_pattern_blocks documents (any type)."""
    alerts_full_tx = list(alerts_full_tx)
    truths = [alert_truth(txs, laundering_tx) for txs in alerts_full_tx]
    n = len(truths)
    sus = sum(1 for t in truths if t["is_suspicious"])
    ptype = pattern_type_for(direction)
    caught_tx = {t for txs in alerts_full_tx for t in txs}
    matching = [b for b in blocks if b["pattern_type"] == ptype]
    caught = sum(1 for b in matching if caught_tx.intersection(b["tx_ids"]))
    return {
        "alert_count": n, "suspicious_alert_count": sus,
        "alert_precision": (sus / n) if n else None, "false_alarm_count": n - sus,
        "pattern_type": ptype,
        "pattern_recall": {"caught": caught, "total": len(matching),
                           "recall": (caught / len(matching)) if matching else None},
        "duration_seconds": round(duration_seconds, 3), "slice_hours": slice_hours,
    }

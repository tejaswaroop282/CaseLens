"""Fact sheet F0-F10 (docs/03 section 3). All numbers come from code; facts use ALL window transactions.

Rounding: amounts 2 decimals, ratios 4 decimals, hours 2 decimals. Times UTC."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from statistics import mean, pstdev

from app.models import Fact
from app.tools import get_alert, get_prior_activity, get_scenario, top_counterparties, window_rows


class AlertNotFound(Exception):
    pass


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def data_origin_of(alert: dict):
    """Buckets count from data_origin, so origin = window_start - bucket * window_hours."""
    return alert["window_start"] - timedelta(hours=alert["bucket"] * alert["window_hours"])


def build_fact_sheet(db, alert_id: str) -> tuple[list[Fact], dict, dict]:
    """Returns (facts, alert view, scenario view)."""
    alert = get_alert(db, alert_id)
    if alert is None:
        raise AlertNotFound(alert_id)
    scenario = get_scenario(db, alert["scenario_id"]) or {}
    params = (scenario.get("spec") or {}).get("params") or {}
    formats = params.get("payment_formats")
    d = alert["direction"]
    rows = window_rows(db, alert["account_id"], d, alert["window_start"], alert["window_end"], formats)
    origin = data_origin_of(alert)
    F = []

    def add(fid, label, value, unit=None, source="facts.window_stats"):
        F.append(Fact(id=fid, label=label, value=value, unit=unit, source=source))

    add("F0", "rule context", {"direction": d, "min_counterparties": params.get("min_counterparties"),
                               "window_hours": alert["window_hours"], "window_start": _iso(alert["window_start"]),
                               "window_end": _iso(alert["window_end"]), "payment_formats": formats},
        source="alerts+scenarios")
    add("F1", "transaction count in window", len(rows), "transactions")
    window_cps = {r["cp"] for r in rows}
    add("F2", "distinct counterparties in window", len(window_cps), "accounts")
    totals: dict[str, float] = {}
    for r in rows:
        totals[r["currency"]] = totals.get(r["currency"], 0.0) + r["amount"]
    add("F3", "total amount per currency", {k: round(v, 2) for k, v in sorted(totals.items())},
        "paid" if d == "out" else "received")
    span = (rows[-1]["ts"] - rows[0]["ts"]).total_seconds() / 3600 if len(rows) > 1 else 0.0
    add("F4", "time span in hours", round(span, 2), "hours")
    add("F5", "payment format counts", dict(sorted(Counter(r["format"] for r in rows).items())), "transactions")

    history = alert["window_start"] > origin
    prior = (get_prior_activity(db, alert["account_id"], d, alert["window_start"], origin) if history
             else {"prior_tx_count": 0, "prior_distinct_counterparties": 0, "prior_days_observed": 0,
                   "prior_counterparties": []})
    add("F6", "prior activity (same direction, before the window)",
        {"history_available": history, "prior_tx_count": prior["prior_tx_count"],
         "prior_distinct_counterparties": prior["prior_distinct_counterparties"],
         "prior_days_observed": prior["prior_days_observed"]}, source="facts.prior_activity")
    f7 = None
    if history and prior["prior_tx_count"] > 0 and window_cps:
        f7 = round(len(window_cps & set(prior["prior_counterparties"])) / len(window_cps), 4)
    add("F7", "repeat counterparty share", f7, "ratio", source="facts.prior_activity")

    bank_counts = Counter(r["cp_bank"] for r in rows)
    add("F8", "counterparty bank diversity",
        {"distinct_banks": len(bank_counts),
         "top_bank_share": round(bank_counts.most_common(1)[0][1] / len(rows), 4) if rows else None})

    f9 = None
    if rows:
        cur = Counter(r["currency"] for r in rows).most_common(1)[0][0]
        amounts = [r["amount"] for r in rows if r["currency"] == cur]
        m = mean(amounts)
        if len(amounts) >= 2 and m != 0:
            sd = pstdev(amounts)
            f9 = {"currency": cur, "n": len(amounts), "mean": round(m, 2), "std": round(sd, 2), "cv": round(sd / m, 4)}
    add("F9", "amount regularity", f9)
    add("F10", "top counterparties", top_counterparties(rows, 5), source="facts.counterparties")
    return F, alert, scenario

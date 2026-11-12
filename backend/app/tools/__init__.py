"""Read-only, allow-listed data access for the facts builder and the investigation nodes (docs/03 section 2).

Tools may read only `alerts`, `scenarios`, `stg_transactions` and the Chroma collection `reg_docs`.
The evaluation-only collections (stg_labels, stg_pattern_blocks, alert_truth) are NOT on the list.
Every tool returns an explicit field whitelist (never whole documents) and never raw transaction rows."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Callable, Optional

from pymongo.collection import Collection

ALLOWED_COLLECTIONS = frozenset({"alerts", "scenarios", "stg_transactions"})
ALERT_FIELDS = ("alert_id", "scenario_id", "run_id", "direction", "account_id", "bucket", "window_hours",
                "window_start", "window_end", "distinct_counterparties", "tx_count", "first_ts", "last_ts", "status")
SCENARIO_FIELDS = ("scenario_id", "spec", "status")
MAX_TOP_N, MAX_K, MAX_CHUNK_CHARS = 10, 8, 1200


def tool_collection(db, name: str) -> Collection:
    if name not in ALLOWED_COLLECTIONS:
        raise PermissionError(f"tools may not read collection {name!r}")
    return db[name]


def _project(fields) -> dict:
    return {"_id": 0, **{f: 1 for f in fields}}


# ---------------- direction helpers ----------------
def sides(direction: str) -> dict[str, str]:
    """For 'out' the counterparty is the receiver and amounts are paid; for 'in' the reverse."""
    if direction == "out":
        return {"key": "from_account", "cp": "to_account", "cp_bank": "to_bank",
                "amount": "amount_paid", "currency": "currency_paid"}
    if direction == "in":
        return {"key": "to_account", "cp": "from_account", "cp_bank": "from_bank",
                "amount": "amount_received", "currency": "currency_received"}
    raise ValueError(f"unsupported direction {direction!r}")


# ---------------- tools ----------------
def get_alert(db, alert_id: str) -> Optional[dict]:
    return tool_collection(db, "alerts").find_one({"alert_id": alert_id}, _project(ALERT_FIELDS))


def get_scenario(db, scenario_id: str) -> Optional[dict]:
    return tool_collection(db, "scenarios").find_one({"scenario_id": scenario_id}, _project(SCENARIO_FIELDS))


def window_rows(db, account_id: str, direction: str, start: datetime, end: datetime,
                payment_formats: Optional[list[str]] = None) -> list[dict]:
    """Internal: projected transaction fields for one account/window. Used only by code (facts); the LLM
    never sees raw rows."""
    sd = sides(direction)
    q: dict[str, Any] = {sd["key"]: account_id, "ts": {"$gte": start, "$lt": end}}
    if payment_formats:
        q["payment_format"] = {"$in": list(payment_formats)}
    proj = {"_id": 0, "ts": 1, "payment_format": 1, sd["cp"]: 1, sd["cp_bank"]: 1, sd["amount"]: 1, sd["currency"]: 1}
    return [{"ts": r["ts"], "format": r["payment_format"], "cp": r[sd["cp"]], "cp_bank": r[sd["cp_bank"]],
             "amount": float(r[sd["amount"]]), "currency": r[sd["currency"]]}
            for r in tool_collection(db, "stg_transactions").find(q, proj).sort("ts", 1)]


def get_window_stats(db, alert_id: str) -> Optional[dict]:
    """Aggregates over the alert window (no raw rows)."""
    alert = get_alert(db, alert_id)
    if alert is None:
        return None
    sc = get_scenario(db, alert["scenario_id"]) or {}
    formats = ((sc.get("spec") or {}).get("params") or {}).get("payment_formats")
    rows = window_rows(db, alert["account_id"], alert["direction"], alert["window_start"], alert["window_end"], formats)
    totals: dict[str, float] = {}
    for r in rows:
        totals[r["currency"]] = totals.get(r["currency"], 0.0) + r["amount"]
    return {"alert_id": alert_id, "tx_count": len(rows), "distinct_counterparties": len({r["cp"] for r in rows}),
            "amount_per_currency": {k: round(v, 2) for k, v in totals.items()},
            "formats": dict(Counter(r["format"] for r in rows)),
            "counterparty_banks": len({r["cp_bank"] for r in rows}),
            "first_ts": rows[0]["ts"] if rows else None, "last_ts": rows[-1]["ts"] if rows else None}


def get_prior_activity(db, account_id: str, direction: str, before_ts: datetime, origin: datetime) -> dict:
    """Earlier same-direction activity in [origin, before_ts) (counts only)."""
    rows = window_rows(db, account_id, direction, origin, before_ts)
    return {"prior_tx_count": len(rows), "prior_distinct_counterparties": len({r["cp"] for r in rows}),
            "prior_days_observed": len({r["ts"].date() for r in rows}),
            "prior_counterparties": sorted({r["cp"] for r in rows})}


def get_counterparties(db, alert_id: str, top_n: int = 5) -> list[dict]:
    top_n = max(1, min(int(top_n), MAX_TOP_N))
    alert = get_alert(db, alert_id)
    if alert is None:
        return []
    sc = get_scenario(db, alert["scenario_id"]) or {}
    formats = ((sc.get("spec") or {}).get("params") or {}).get("payment_formats")
    rows = window_rows(db, alert["account_id"], alert["direction"], alert["window_start"], alert["window_end"], formats)
    return top_counterparties(rows, top_n)


def top_counterparties(rows: list[dict], top_n: int = 5) -> list[dict]:
    """Sorted by tx_count desc, then by amount in the most frequent currency desc. Amounts are summed per
    currency only (PROJECT_REPORT pitfall 6), so total_amount is {currency: total}."""
    main_cur = Counter(r["currency"] for r in rows).most_common(1)[0][0] if rows else None
    agg: dict[str, dict] = {}
    for r in rows:
        a = agg.setdefault(r["cp"], {"account_id": r["cp"], "tx_count": 0, "total_amount": {}})
        a["tx_count"] += 1
        a["total_amount"][r["currency"]] = a["total_amount"].get(r["currency"], 0.0) + r["amount"]
    out = sorted(agg.values(), key=lambda a: (-a["tx_count"], -a["total_amount"].get(main_cur, 0.0), a["account_id"]))
    for a in out:
        a["total_amount"] = {k: round(v, 2) for k, v in a["total_amount"].items()}
    return out[:top_n]


# ---------------- regulatory documents (Chroma) ----------------
_store_factory: Optional[Callable[[], Any]] = None


def set_store_factory(factory: Optional[Callable[[], Any]]) -> None:
    """Tests install a fake store (no Chroma, no embeddings)."""
    global _store_factory
    _store_factory = factory


def _store():
    if _store_factory is not None:
        return _store_factory()
    from pipeline.ingest_docs import get_store
    return get_store()


def search_reg_docs(query: str, k: int = 4) -> list[dict]:
    k = max(1, min(int(k), MAX_K))
    out = []
    for doc, score in _store().similarity_search_with_score(query, k=k):
        m = doc.metadata or {}
        out.append({"chunk_id": m.get("chunk_id"), "title": m.get("title"), "page": m.get("page"),
                    "source_url": m.get("source_url"), "text": doc.page_content[:MAX_CHUNK_CHARS],
                    "score": round(float(score), 4)})
    return out


def get_chunk(chunk_id: str) -> Optional[dict]:
    got = _store().get(ids=[chunk_id], include=["documents", "metadatas"])
    if not got or not got.get("ids"):
        return None
    m = got["metadatas"][0] or {}
    return {"chunk_id": chunk_id, "title": m.get("title"), "page": m.get("page"),
            "source_url": m.get("source_url"), "text": got["documents"][0]}

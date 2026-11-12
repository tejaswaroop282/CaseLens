"""Code evaluators (docs/05). Plain functions returning {"key", "score"}; score None means 'skipped'.

`out` is the target's output: {"spec": <ScenarioSpec dict> | None, "error": str | None, ...}."""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Optional

DATA_DIR = Path(__file__).parent / "data"


def load_jsonl(name: str) -> list[dict]:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _spec(out: dict) -> Optional[dict]:
    return out.get("spec") if out else None


def schema_valid(out: dict, expected: dict) -> dict:
    return {"key": "schema_valid", "score": 1 if _spec(out) is not None else 0}


def direction_match(out: dict, expected: dict) -> dict:
    s = _spec(out)
    if s is None:
        return {"key": "direction_match", "score": 0}
    if expected.get("allow_valid_spec") and s["direction"] is not None:
        return {"key": "direction_match", "score": 1}             # any in-bounds spec is acceptable here
    return {"key": "direction_match", "score": 1 if s["direction"] == expected["direction"] else 0}


def _meets(value, rule: dict) -> bool:
    if "exact" in rule:
        return value == rule["exact"]
    if "range" in rule:
        lo, hi = rule["range"]
        return value is not None and lo <= value <= hi
    if "contains" in rule:
        return value is not None and rule["contains"] in value
    raise ValueError(f"unknown rule {rule}")


def params_in_expectation(out: dict, expected: dict) -> dict:
    if expected["direction"] is None:
        return {"key": "params_in_expectation", "score": None}
    s = _spec(out)
    p = (s or {}).get("params") or {}
    checks = {k: v for k, v in expected.items() if k in ("min_counterparties", "window_hours", "payment_formats")}
    ok = bool(p) and all(_meets(p.get(k), rule) for k, rule in checks.items())
    return {"key": "params_in_expectation", "score": 1 if ok else 0}


def correct_rejection(out: dict, expected: dict) -> dict:
    if expected["direction"] is not None:
        return {"key": "correct_rejection", "score": None}
    s = _spec(out)
    if s is None:
        return {"key": "correct_rejection", "score": 0}
    ok = s["direction"] is None or bool(expected.get("allow_valid_spec"))
    return {"key": "correct_rejection", "score": 1 if ok else 0}


EVALUATORS = (schema_valid, direction_match, params_in_expectation, correct_rejection)


def score_row(out: dict, expected: dict) -> dict[str, Optional[int]]:
    return {r["key"]: r["score"] for r in (ev(out, expected) for ev in EVALUATORS)}


def summarize(scores: list[dict[str, Optional[int]]]) -> dict[str, Optional[float]]:
    keys = sorted({k for s in scores for k in s})
    out = {}
    for k in keys:
        vals = [s[k] for s in scores if s.get(k) is not None]
        out[k] = round(mean(vals), 4) if vals else None
        out[f"{k}_n"] = len(vals)
    return out

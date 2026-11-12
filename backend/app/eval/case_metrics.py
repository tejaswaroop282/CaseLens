"""Eval set 2 helpers (docs/05 section 4): splits and metrics. Evaluation code: may read ground truth."""
from __future__ import annotations

import random
from statistics import mean
from typing import Optional

from app.investigation.checker import check_claim
from app.models import CaseFile, Fact

LEGIT = "likely_legitimate"


# ---------------- splits ----------------
def make_splits(truth: list[dict], seed: int, dev_n: int = 10, eval_n: int = 30) -> dict:
    """Disjoint, balanced (half suspicious) when possible. truth rows: {alert_id, is_suspicious}.
    If there are too few of one class, all of them are used and the shortfall is reported."""
    rnd = random.Random(seed)
    sus = sorted(t["alert_id"] for t in truth if t["is_suspicious"])
    non = sorted(t["alert_id"] for t in truth if not t["is_suspicious"])
    rnd.shuffle(sus); rnd.shuffle(non)
    need = {"dev": (dev_n // 2, dev_n - dev_n // 2), "eval": (eval_n // 2, eval_n - eval_n // 2)}
    out, notes = {}, []
    for split in ("dev", "eval"):                       # dev first: prompt work needs it most
        ns, nn = need[split]
        take_s, take_n = sus[:ns], non[:nn]
        sus, non = sus[ns:], non[nn:]
        if len(take_s) < ns or len(take_n) < nn:
            notes.append(f"{split}: wanted {ns} suspicious / {nn} not, got {len(take_s)} / {len(take_n)}")
        out[split] = [{"alert_id": a, "is_suspicious": True} for a in take_s] + \
                     [{"alert_id": a, "is_suspicious": False} for a in take_n]
        rnd.shuffle(out[split])
    return {"dev": out["dev"], "eval": out["eval"], "notes": notes}


# ---------------- verdicts per system ----------------
def verdict_from_case(case: Optional[dict]) -> str:
    """System C: cases that end needs_human_rewrite or failed count as needs_review."""
    if not case or case.get("status") not in ("checked", "decided") or not case.get("case_file"):
        return "needs_review"
    return case["case_file"]["verdict"]


def citation_validity(case: dict, id_pattern: Optional[str] = None) -> tuple[int, int]:
    """(valid claims, total claims): re-run the checker per claim on the final draft."""
    import re
    cf = case.get("case_file")
    if not cf:
        return 0, 0
    facts = {f["id"]: Fact.model_validate(f) for f in case.get("facts", [])}
    chunks = set(case.get("retrieved_chunk_ids") or [])
    model = CaseFile.model_validate(cf)
    claims = [*model.claims, *model.benign_explanations, *model.typology_context]
    kw = {"id_re": re.compile(id_pattern)} if id_pattern else {}
    valid = sum(1 for c in claims if not check_claim(c, facts, chunks, "c", **kw))
    return valid, len(claims)


# ---------------- metrics ----------------
def _rate(num: int, den: int) -> Optional[float]:
    return round(num / den, 4) if den else None


def system_metrics(rows: list[dict]) -> dict:
    """rows: {alert_id, is_suspicious, verdict, [case]}. Case-based metrics only when cases are present."""
    sus = [r for r in rows if r["is_suspicious"]]
    non = [r for r in rows if not r["is_suspicious"]]
    m = {
        "n": len(rows), "n_suspicious": len(sus), "n_not_suspicious": len(non),
        "false_clear_rate": _rate(sum(r["verdict"] == LEGIT for r in sus), len(sus)),
        "false_clears": [r["alert_id"] for r in sus if r["verdict"] == LEGIT],
        "auto_clear_rate": _rate(sum(r["verdict"] == LEGIT for r in non), len(non)),
        "review_load": _rate(sum(r["verdict"] != LEGIT for r in rows), len(rows)),
    }
    cases = [r["case"] for r in rows if r.get("case")]
    if cases:
        n = len(cases)
        m["checker_first_pass_rate"] = _rate(sum(c.get("status") in ("checked", "decided")
                                                 and (c.get("checker") or {}).get("attempts") == 1 for c in cases), n)
        m["checker_after_retry_rate"] = _rate(sum(c.get("status") in ("checked", "decided") for c in cases), n)
        m["needs_rewrite_rate"] = _rate(sum(c.get("status") == "needs_human_rewrite" for c in cases), n)
        m["failed_rate"] = _rate(sum(c.get("status") == "failed" for c in cases), n)
        cv = [citation_validity(c) for c in cases]
        m["citation_validity"] = _rate(sum(v for v, _ in cv), sum(t for _, t in cv))
        m["avg_latency_s"] = round(mean((c.get("timings") or {}).get("total_seconds", 0) for c in cases), 2)
        m["avg_tokens"] = {"input": round(mean(c["tokens"]["input"] for c in cases)),
                           "output": round(mean(c["tokens"]["output"] for c in cases))}
        m["total_tokens"] = {"input": sum(c["tokens"]["input"] for c in cases),
                             "output": sum(c["tokens"]["output"] for c in cases)}
    return m


def tune_baseline(rows: list[dict], facts_by_alert: dict, cv_grid=(0.01, 0.02, 0.05, 0.1, 0.2),
                  repeat_grid=(0.3, 0.5, 0.7, 0.9)) -> dict:
    """Dev split only. Highest auto-clear with zero false-clears; ties go to the stricter setting."""
    from app.investigation.triage_baseline import triage
    best = None
    for cv in cv_grid:
        for rep in sorted(repeat_grid, reverse=True):
            scored = [{**r, "verdict": triage(facts_by_alert[r["alert_id"]], cv, rep)} for r in rows]
            m = system_metrics(scored)
            if (m["false_clear_rate"] or 0) > 0:
                continue
            key = (m["auto_clear_rate"] or 0, -cv, rep)
            if best is None or key > best[0]:
                best = (key, {"cv_max": cv, "repeat_min": rep, "dev_auto_clear_rate": m["auto_clear_rate"]})
    return best[1] if best else {"cv_max": 0.0, "repeat_min": 1.01, "dev_auto_clear_rate": 0.0,
                                 "note": "no setting avoided false-clears on dev; baseline never clears"}

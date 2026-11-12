"""Eval set 2 tests (docs/05 section 5)."""
from app.eval.case_metrics import citation_validity, make_splits, system_metrics, tune_baseline, verdict_from_case
from app.eval.run_case_eval import check_budget
from app.models import Fact
from app.scripts.estimate_cost import spend


def truth(n_sus, n_non):
    return [{"alert_id": f"s{i}", "is_suspicious": True} for i in range(n_sus)] + \
           [{"alert_id": f"n{i}", "is_suspicious": False} for i in range(n_non)]


def test_dev_and_eval_splits_are_disjoint():
    sp = make_splits(truth(40, 200), seed=42)
    dev, ev = {r["alert_id"] for r in sp["dev"]}, {r["alert_id"] for r in sp["eval"]}
    assert len(dev) == 10 and len(ev) == 30 and not dev & ev
    assert sp == make_splits(truth(40, 200), seed=42)                    # deterministic with the seed


def test_splits_balanced_when_possible():
    sp = make_splits(truth(40, 200), seed=42)
    assert sum(r["is_suspicious"] for r in sp["dev"]) == 5 and sum(r["is_suspicious"] for r in sp["eval"]) == 15
    short = make_splits(truth(8, 200), seed=42)                           # too few suspicious: use all, report it
    assert sum(r["is_suspicious"] for r in short["dev"]) == 5
    assert sum(r["is_suspicious"] for r in short["eval"]) == 3 and short["notes"]


def test_dry_run_refuses_when_budget_too_small():
    ok, est = check_budget(30, {"input": 10_000, "output": 10_000})
    assert not ok and est["input"] == 30 * 11_500
    assert check_budget(1, {"input": 1_000_000, "output": 1_000_000})[0]


def rows(verdicts):
    return [{"alert_id": f"a{i}", "is_suspicious": s, "verdict": v} for i, (s, v) in enumerate(verdicts)]


def test_system_metrics_rates():
    m = system_metrics(rows([(True, "likely_legitimate"), (True, "needs_review"),
                             (False, "likely_legitimate"), (False, "needs_review")]))
    assert m["false_clear_rate"] == 0.5 and m["false_clears"] == ["a0"]
    assert m["auto_clear_rate"] == 0.5 and m["review_load"] == 0.5
    a = system_metrics(rows([(True, "needs_review"), (False, "needs_review")]))
    assert (a["false_clear_rate"], a["auto_clear_rate"], a["review_load"]) == (0.0, 0.0, 1.0)


def test_failed_and_rewrite_cases_count_as_needs_review():
    assert verdict_from_case({"status": "needs_human_rewrite", "case_file": {"verdict": "likely_legitimate"}}) == "needs_review"
    assert verdict_from_case({"status": "failed", "case_file": None}) == "needs_review"
    assert verdict_from_case(None) == "needs_review"
    assert verdict_from_case({"status": "decided", "case_file": {"verdict": "likely_suspicious"}}) == "likely_suspicious"


def test_citation_validity_per_claim():
    case = {"facts": [{"id": "F1", "label": "n", "value": 14, "unit": None, "source": "x"}], "retrieved_chunk_ids": [],
            "case_file": {"verdict": "needs_review", "summary": "s", "limitations": "",
                          "claims": [{"text": "14 payments.", "fact_ids": ["F1"], "chunk_ids": []},
                                     {"text": "15 payments.", "fact_ids": ["F1"], "chunk_ids": []}]}}
    assert citation_validity(case) == (1, 2)


def test_tune_baseline_never_accepts_false_clears():
    f = lambda f7, cv: {"F7": Fact(id="F7", label="", value=f7, source=""),       # noqa: E731
                        "F9": Fact(id="F9", label="", value={"cv": cv}, source="")}
    data = [{"alert_id": "s", "is_suspicious": True}, {"alert_id": "n1", "is_suspicious": False},
            {"alert_id": "n2", "is_suspicious": False}]
    facts = {"s": f(0.8, 0.15), "n1": f(0.9, 0.01), "n2": f(0.6, 0.04)}
    best = tune_baseline(data, facts)
    assert best["cv_max"] < 0.15 and best["dev_auto_clear_rate"] == 1.0          # clears both, never the suspicious one


def test_spend():
    assert round(spend(1_000_000, 500_000, 0.1, 0.4), 4) == 0.3

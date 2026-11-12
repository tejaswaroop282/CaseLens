"""Eval data and evaluator tests (docs/05 section 5)."""
from app.eval.evaluators import load_jsonl, score_row, summarize
from app.eval.run_scenario_eval import estimate


def test_eval_files_are_valid_jsonl():
    rows = load_jsonl("scenario_parse.jsonl")
    assert len(rows) == 20 and len({r["id"] for r in rows}) == 20
    assert sum(r["expected"]["direction"] is None for r in rows) == 8
    for r in rows:
        assert r["intent"] and r["expected"]["direction"] in ("in", "out", None)
        w = r["expected"].get("window_hours", {})
        assert max(w.get("range", [w.get("exact", 0)])) <= 24          # every window fits a 24-hour slice


def spec(direction, n=None, w=None, formats=None, reason=None):
    params = None if direction is None else {"min_counterparties": n, "window_hours": w, "payment_formats": formats}
    return {"spec": {"direction": direction, "params": params, "unsupported_reason": reason}, "error": None}


def test_evaluators_exact_range_contains():
    exp = {"direction": "out", "min_counterparties": {"exact": 10}, "window_hours": {"range": [12, 24]},
           "payment_formats": {"contains": "Wire"}}
    assert score_row(spec("out", 10, 24, ["Wire"]), exp) == {
        "schema_valid": 1, "direction_match": 1, "params_in_expectation": 1, "correct_rejection": None}
    assert score_row(spec("out", 10, 6, ["Wire"]), exp)["params_in_expectation"] == 0
    assert score_row(spec("out", 10, 24, None), exp)["params_in_expectation"] == 0
    assert score_row(spec("in", 10, 24, ["Wire"]), exp)["direction_match"] == 0


def test_evaluators_rejection_and_failures():
    exp = {"direction": None}
    assert score_row(spec(None, reason="x"), exp) == {
        "schema_valid": 1, "direction_match": 1, "params_in_expectation": None, "correct_rejection": 1}
    assert score_row(spec("out", 10, 24), exp)["correct_rejection"] == 0
    failed = {"spec": None, "error": "parse_failed"}
    assert score_row(failed, exp) == {"schema_valid": 0, "direction_match": 0, "params_in_expectation": None,
                                      "correct_rejection": 0}
    injection = {"direction": None, "allow_valid_spec": True}       # row 17: null, or any in-bounds spec
    assert score_row(spec("out", 3, 24), injection)["correct_rejection"] == 1


def test_summary_skips_none_and_estimate():
    s = summarize([{"a": 1, "b": None}, {"a": 0, "b": 1}])
    assert s == {"a": 0.5, "a_n": 2, "b": 1.0, "b_n": 1}
    assert estimate(20) == {"input": 15600, "output": 5200}

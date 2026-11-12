import pytest
from pydantic import ValidationError
from models import *
from checker import check_case_file
from graph import build_graph

FACTS = [Fact(id="F1", label="tx count", value=14, source="x"),
         Fact(id="F2", label="distinct counterparties", value=12, source="x"),
         Fact(id="F3", label="total", value={"USD": 15234.567}, unit="USD", source="x"),
         Fact(id="F4", label="span hours", value=5.5, source="x"),
         Fact(id="F7", label="share repeat", value=0.4, source="x"),
         Fact(id="F10", label="top", value=["80AB12CD4", "80AB99EE1"], source="x")]

def cf(text, ids=("F1",), verdict="needs_review", benign=None):
    return CaseFile(verdict=verdict, summary="s", claims=[Claim(text=text, fact_ids=list(ids))],
                    benign_explanations=benign or [])

def test_spec_ok():
    s = ScenarioSpec(direction="out", params=ScenarioParams(min_counterparties=10, window_hours=24))
    assert s.direction == "out"
def test_spec_unsupported_needs_reason():
    with pytest.raises(ValidationError): ScenarioSpec(direction=None)
    assert ScenarioSpec(direction=None, unsupported_reason="cash structuring is not supported").params is None
def test_spec_bounds():
    with pytest.raises(ValidationError): ScenarioParams(min_counterparties=2, window_hours=24)
    with pytest.raises(ValidationError): ScenarioParams(min_counterparties=201, window_hours=24)
    with pytest.raises(ValidationError): ScenarioParams(min_counterparties=10, window_hours=0)

def test_checker_pass():
    r = check_case_file(cf("The account made 14 payments to 12 different accounts in 5.5 hours.", ("F1","F2","F4")), FACTS, set())
    assert r.passed, r.errors
def test_checker_wrong_number():
    r = check_case_file(cf("The account made 15 payments.", ("F1",)), FACTS, set())
    assert not r.passed and "15" in r.errors[0]
def test_checker_rounding_and_commas():
    assert check_case_file(cf("Total sent was 15,235 USD.", ("F3",)), FACTS, set()).passed
    assert check_case_file(cf("Total sent was 15234.57 USD.", ("F3",)), FACTS, set()).passed
    assert not check_case_file(cf("Total sent was 15,300 USD.", ("F3",)), FACTS, set()).passed
def test_checker_percent():
    assert check_case_file(cf("40% of counterparties were seen before.", ("F7",)), FACTS, set()).passed
    assert not check_case_file(cf("60% of counterparties were seen before.", ("F7",)), FACTS, set()).passed
def test_checker_unknown_ids_and_missing_refs():
    assert not check_case_file(cf("Something.", ("F99",)), FACTS, set()).passed
    bad = CaseFile(verdict="needs_review", summary="s", claims=[Claim(text="No refs here")])
    assert not check_case_file(bad, FACTS, set()).passed
def test_checker_invented_account_id():
    assert not check_case_file(cf("Money went to 11223344AA.", ("F10",)), FACTS, set()).passed
    assert check_case_file(cf("Money went to 80AB12CD4.", ("F10",)), FACTS, set()).passed
def test_checker_legit_needs_benign_and_no_red_flag():
    assert not check_case_file(cf("14 payments.", verdict="likely_legitimate"), FACTS, set()).passed
    ben = [Claim(text="Amounts were regular.", fact_ids=["F3"])]
    assert check_case_file(cf("14 payments.", verdict="likely_legitimate", benign=ben), FACTS, set()).passed
    assert not check_case_file(cf("14 payments.", verdict="likely_legitimate", benign=ben), FACTS, set(), hard_red_flag=True).passed

def make_nodes(fail_times):
    calls = {"drafter": 0}
    def drafter(s):
        calls["drafter"] += 1
        return {"draft": {"n": calls["drafter"]}, "retries": calls["drafter"] - 1}
    def checker(s):
        return {"checker_errors": ["bad"] if calls["drafter"] <= fail_times else []}
    return calls, {
        "build_facts": lambda s: {"facts": [1]}, "typology_agent": lambda s: {"typology_notes": ["t"]},
        "benign_agent": lambda s: {"benign_notes": ["b"]}, "drafter": drafter, "evidence_checker": checker}
def test_graph_pass_first_time():
    calls, nodes = make_nodes(0); out = build_graph(nodes).invoke({"alert": {}, "retries": 0})
    assert out["status"] == "checked" and calls["drafter"] == 1
def test_graph_retry_then_pass():
    calls, nodes = make_nodes(1); out = build_graph(nodes).invoke({"alert": {}, "retries": 0})
    assert out["status"] == "checked" and calls["drafter"] == 2
def test_graph_give_up():
    calls, nodes = make_nodes(5); out = build_graph(nodes).invoke({"alert": {}, "retries": 0})
    assert out["status"] == "needs_human_rewrite" and calls["drafter"] == 2

def test_checker_typology_needs_chunks_and_no_numbers():
    ok = CaseFile(verdict="needs_review", summary="s", claims=[Claim(text="14 payments.", fact_ids=["F1"])],
                  typology_context=[Claim(text="Guidance lists rapid dispersal of funds as an indicator.", chunk_ids=["c_1"])])
    assert check_case_file(ok, FACTS, {"c_1"}).passed
    no_chunk = ok.model_copy(update={"typology_context": [Claim(text="Rapid dispersal.", fact_ids=["F1"])]})
    assert not check_case_file(no_chunk, FACTS, {"c_1"}).passed
    with_num = ok.model_copy(update={"typology_context": [Claim(text="Guidance says over 10 accounts is suspicious.", chunk_ids=["c_1"])]})
    assert not check_case_file(with_num, FACTS, {"c_1"}).passed
    bad_chunk = ok.model_copy(update={"typology_context": [Claim(text="Rapid dispersal.", chunk_ids=["c_9"])]})
    assert not check_case_file(bad_chunk, FACTS, {"c_1"}).passed

"""Investigation tests (docs/03 section 10), including the four required leakage tests. Test-only fixtures."""
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from langchain_core.documents import Document

from app import llm, tools
from app.budget import TokenLedger
from app.config import get_settings
from app.investigation import prompts as P
from app.investigation.checker import check_case_file
from app.investigation.facts import build_fact_sheet
from app.investigation.service import execute_investigation, start_investigation
from app.investigation.triage_baseline import triage
from app.models import BenignNotes, CaseFile, Claim, Fact, TypologyNotes
from tests.fakes import FakeToolChat

O = datetime(2022, 9, 1, tzinfo=timezone.utc)
D2 = O + timedelta(hours=24)
FORBIDDEN = ("is_laundering", "pattern_type", "pattern_id", "is_suspicious", "n_laundering_tx", "laundering")
CHUNKS = ["c_d1_0001_000", "c_d1_0002_000"]


def tx(i, ts, frm, to, amt, cur="US Dollar", fmt="ACH", to_bank="B1"):
    return {"tx_id": f"t{i}", "ts": ts, "from_bank": "B0", "from_account": frm, "to_bank": to_bank,
            "to_account": to, "amount_paid": amt, "currency_paid": cur, "amount_received": amt,
            "currency_received": cur, "payment_format": fmt}


ROWS = [
    # prior day (bucket 0) for account A, direction out
    tx("p1", O + timedelta(hours=2), "A", "R1", 100.0), tx("p2", O + timedelta(hours=3), "A", "R2", 100.0),
    tx("p3", O + timedelta(hours=4), "A", "R9", 10.0),
    # alert window (bucket 1)
    tx(1, D2 + timedelta(hours=1), "A", "R1", 100.0, to_bank="B1"),
    tx(2, D2 + timedelta(hours=2), "A", "R2", 100.0, to_bank="B1"),
    tx(3, D2 + timedelta(hours=3), "A", "R3", 100.0, fmt="Wire", to_bank="B2"),
    tx(4, D2 + timedelta(hours=5, minutes=30), "A", "R4", 130.0, fmt="Wire", to_bank="B3"),
    tx(5, D2 + timedelta(hours=6), "A", "R4", 50.0, cur="Euro", fmt="Cash", to_bank="B3"),
    # noise: other sender, and money INTO A (not same direction)
    tx("n1", D2 + timedelta(hours=1), "Z", "R1", 999.0), tx("n2", D2 + timedelta(hours=2), "Q", "A", 5.0),
    # a lone single-transaction window for account S (bucket 1)
    tx("s1", D2 + timedelta(hours=7), "S", "R7", 42.0),
]


def seed(db, formats=None, bucket=1, account="A", alert_id="a1"):
    db.stg_transactions.insert_many([dict(r) for r in ROWS])
    db.scenarios.insert_one({"scenario_id": "s1", "status": "completed", "spec": {
        "direction": "out", "params": {"min_counterparties": 3, "window_hours": 24, "payment_formats": formats},
        "legitimate_lookalikes": [], "rationale": "", "unsupported_reason": None}})
    ws = O + timedelta(hours=24 * bucket)
    db.alerts.insert_one({"alert_id": alert_id, "scenario_id": "s1", "run_id": "r1", "direction": "out",
                          "account_id": account, "bucket": bucket, "window_hours": 24, "window_start": ws,
                          "window_end": ws + timedelta(hours=24), "distinct_counterparties": 4, "tx_count": 5,
                          "tx_ids": ["t1"], "tx_ids_truncated": False, "first_ts": ws, "last_ts": ws, "status": "new"})
    # ground truth lives in the evaluation-only collections (tools must never see it)
    db.stg_labels.insert_one({"tx_id": "t1", "is_laundering": True, "pattern_type": "fan_out", "pattern_id": "P1"})
    db.stg_pattern_blocks.insert_one({"pattern_id": "P1", "pattern_type": "fan_out", "tx_ids": ["t1"]})
    db.alert_truth.insert_one({"alert_id": alert_id, "scenario_id": "s1", "is_suspicious": True, "n_laundering_tx": 1})


class FakeStore:
    def similarity_search_with_score(self, query, k):
        return [(Document(page_content=f"Guidance text {i} about many transfers to many accounts.",
                          metadata={"chunk_id": c, "title": "Doc", "page": i + 1, "source_url": "https://x"}), 0.1)
                for i, c in enumerate(CHUNKS)][:k]


def facts_by_id(db, alert_id="a1"):
    facts, _, _ = build_fact_sheet(db, alert_id)
    return {f.id: f.value for f in facts}


# ---------------- facts ----------------
@pytest.mark.integration
def test_facts_match_pandas_oracle_on_fixture(mongo_db):
    seed(mongo_db)
    f = facts_by_id(mongo_db)
    df = pd.DataFrame(ROWS)
    w = df[(df.from_account == "A") & (df.ts >= D2) & (df.ts < D2 + timedelta(hours=24))]
    assert f["F1"] == len(w) == 5
    assert f["F2"] == w.to_account.nunique() == 4
    assert f["F3"] == w.groupby("currency_paid").amount_paid.sum().round(2).to_dict() == {"Euro": 50.0, "US Dollar": 430.0}
    assert f["F4"] == 5.0
    assert f["F5"] == {"ACH": 2, "Cash": 1, "Wire": 2}
    assert f["F6"] == {"history_available": True, "prior_tx_count": 3, "prior_distinct_counterparties": 3,
                       "prior_days_observed": 1}
    assert f["F7"] == 0.5                                                    # {R1,R2} of {R1..R4} seen before
    assert f["F8"] == {"distinct_banks": 3, "top_bank_share": 0.4}
    usd = w[w.currency_paid == "US Dollar"].amount_paid
    assert f["F9"] == {"currency": "US Dollar", "n": 4, "mean": round(usd.mean(), 2),
                       "std": round(usd.std(ddof=0), 2), "cv": round(usd.std(ddof=0) / usd.mean(), 4)}
    assert [c["account_id"] for c in f["F10"]] == ["R4", "R1", "R2", "R3"]
    assert f["F10"][0] == {"account_id": "R4", "tx_count": 2, "total_amount": {"US Dollar": 130.0, "Euro": 50.0}}
    assert f["F0"]["window_start"] == "2022-09-02T00:00:00Z" and f["F0"]["direction"] == "out"


@pytest.mark.integration
def test_f6_unavailable_in_first_window(mongo_db):
    seed(mongo_db, bucket=0)
    f = facts_by_id(mongo_db)
    assert f["F6"] == {"history_available": False, "prior_tx_count": 0, "prior_distinct_counterparties": 0,
                       "prior_days_observed": 0}
    assert f["F7"] is None


@pytest.mark.integration
def test_f9_null_for_single_tx(mongo_db):
    seed(mongo_db, account="S", alert_id="aS")
    f = facts_by_id(mongo_db, "aS")
    assert f["F1"] == 1 and f["F9"] is None and f["F4"] == 0.0


@pytest.mark.integration
def test_facts_respect_payment_format_filter(mongo_db):
    seed(mongo_db, formats=["ACH", "Wire"])
    f = facts_by_id(mongo_db)
    assert f["F1"] == 4 and f["F3"] == {"US Dollar": 430.0} and "Cash" not in f["F5"]


# ---------------- graph with a scripted fake LLM ----------------
GOOD = CaseFile(verdict="needs_review", summary="Fan-out activity to several accounts.",
                claims=[Claim(text="The account made 5 payments to 4 different accounts in 5.0 hours.",
                              fact_ids=["F1", "F2", "F4"]),
                        Claim(text="Guidance lists rapid dispersal to many accounts as an indicator.",
                              chunk_ids=[CHUNKS[0]])],
                typology_context=[Claim(text="Guidance lists rapid dispersal as an indicator.", chunk_ids=[CHUNKS[0]])],
                missing_evidence=["expected account activity"],
                limitations="The data is simulated.")
BAD = GOOD.model_copy(update={"claims": [Claim(text="The account made 6 payments.", fact_ids=["F1"])]})


def scripted(drafts):
    """Answer by role (the two helpers run in parallel, so call order is not fixed)."""
    drafts = list(drafts)

    def respond(messages):
        system = str(messages[0].content)
        if system == P.TYPOLOGY_SYSTEM:
            return TypologyNotes(items=[Claim(text="Guidance lists rapid dispersal as an indicator.",
                                              chunk_ids=[CHUNKS[0]])])
        if system == P.BENIGN_SYSTEM:
            return BenignNotes(explanations=[Claim(text="Half of the counterparties were seen before (0.5).",
                                                   fact_ids=["F7"])], missing_evidence=["customer occupation"])
        return drafts.pop(0)
    return respond


@pytest.fixture
def env(mongo_db):
    seed(mongo_db)
    usage = []
    led = TokenLedger(max_input=100_000, max_output=100_000,
                      persist=lambda d: (usage.append(d), mongo_db.llm_usage.insert_one(dict(d))))
    llm.set_ledgers(chat=led)
    tools.set_store_factory(FakeStore)
    yield mongo_db, led
    tools.set_store_factory(None)
    llm.set_chat_model_factory(None)


def install(drafts, n_calls=6):
    fake = FakeToolChat(replies=[scripted(drafts)] * n_calls)
    llm.set_chat_model_factory(lambda *a, **k: fake)
    return fake


def run_case(db):
    return execute_investigation(db, start_investigation(db, "a1"))


@pytest.mark.integration
def test_investigation_end_to_end_with_fake_llm(env):
    db, _ = env
    fake = install([GOOD])
    case = run_case(db)
    assert case["status"] == "checked", case.get("checker")
    assert case["checker"] == {"passed": True, "errors": [], "attempts": 1}
    assert case["llm_calls"] == 3 and case["retrieved_chunk_ids"] == CHUNKS
    assert case["case_file"]["verdict"] == "needs_review" and len(case["facts"]) == 11
    assert db.alerts.find_one({"alert_id": "a1"})["status"] == "investigating"          # never auto-closed
    assert len(fake.prompts) == 3


@pytest.mark.integration
def test_bad_number_then_retry_then_pass(env):
    db, _ = env
    fake = install([BAD, GOOD])
    case = run_case(db)
    assert case["status"] == "checked" and case["checker"]["attempts"] == 2 and case["llm_calls"] == 4
    assert "failed these checks" in fake.prompts[-1] and "'6'" in fake.prompts[-1]


@pytest.mark.integration
def test_gives_up_after_one_retry(env):
    db, _ = env
    install([BAD, BAD])
    case = run_case(db)
    assert case["status"] == "needs_human_rewrite" and case["checker"]["attempts"] == 2
    assert case["checker"]["errors"] and case["case_file"]["claims"][0]["text"] == "The account made 6 payments."


@pytest.mark.integration
def test_call_limit_circuit_breaker(env, monkeypatch):
    db, _ = env
    monkeypatch.setattr(get_settings(), "max_llm_calls_per_case", 2)
    install([GOOD])
    case = run_case(db)
    assert case["status"] == "failed" and case["error"]["code"] == "call_limit_exceeded"
    assert case["llm_calls"] == 2


@pytest.mark.integration
def test_case_fails_cleanly_when_token_budget_exhausted(env):
    db, _ = env
    llm.set_ledgers(chat=TokenLedger(max_input=10, max_output=10, used_input=10))
    fake = install([GOOD])
    case = run_case(db)
    assert case["status"] == "failed" and case["error"]["code"] == "llm_budget_exhausted"
    assert fake.prompts == []                                                            # no LLM call made


@pytest.mark.integration
def test_tokens_recorded_per_case(env):
    db, led = env
    install([GOOD])
    case = run_case(db)
    rows = list(db.llm_usage.find({"case_id": case["case_id"]}))
    assert len(rows) == 3 and {r["node"] for r in rows} == {"typology_agent", "benign_agent", "drafter"}
    assert case["tokens"] == {"input": 300, "output": 60} and led.calls == 3


# ---------------- leakage tests (must exist and pass) ----------------
@pytest.mark.integration
def test_tools_never_return_label_keys(env):
    db, _ = env
    outputs = [tools.get_alert(db, "a1"), tools.get_scenario(db, "s1"), tools.get_window_stats(db, "a1"),
               tools.get_prior_activity(db, "A", "out", D2, O), tools.get_counterparties(db, "a1", 10),
               tools.search_reg_docs("anything", 8)]
    blob = json.dumps(outputs, default=str)
    assert all(k not in blob for k in FORBIDDEN)


@pytest.mark.integration
def test_tools_strip_truth_even_if_it_reaches_alerts(env):
    """Defence in depth: if a bug ever wrote truth onto an alert, the tools' field whitelist still drops it."""
    db, _ = env
    db.alerts.update_one({"alert_id": "a1"}, {"$set": {"is_suspicious": True, "n_laundering_tx": 1}})
    blob = json.dumps([tools.get_alert(db, "a1"), tools.get_window_stats(db, "a1")], default=str)
    assert all(k not in blob for k in FORBIDDEN)


def test_tool_collection_allowlist():
    for name in ("stg_labels", "stg_pattern_blocks", "alert_truth", "pipeline_runs"):
        with pytest.raises(PermissionError):
            tools.tool_collection({}, name)


@pytest.mark.integration
def test_prompts_never_contain_label_keys(env):
    db, _ = env
    fake = install([BAD, GOOD])                                     # includes the retry prompt
    run_case(db)
    assert len(fake.prompts) == 4
    for p in fake.prompts:
        assert not any(k in p for k in FORBIDDEN), p[:200]


@pytest.mark.integration
def test_case_documents_have_no_truth_fields(env):
    db, _ = env
    install([GOOD])
    case = run_case(db)
    blob = json.dumps(case, default=str)
    assert not any(k in blob for k in ("is_laundering", "pattern_type", "pattern_id", "is_suspicious",
                                       "n_laundering_tx"))


# ---------------- checker change and baseline (pure) ----------------
def test_checker_accepts_large_amount_without_commas():
    facts = [Fact(id="F3", label="total", value={"US Dollar": 12345678.9}, source="x")]
    ok = CaseFile(verdict="needs_review", summary="s",
                  claims=[Claim(text="Total paid was 12345678.9 US Dollar.", fact_ids=["F3"])])
    assert check_case_file(ok, facts, set()).passed
    bad = ok.model_copy(update={"claims": [Claim(text="Money went to 87654321.", fact_ids=["F3"])]})
    assert not check_case_file(bad, facts, set()).passed          # an invented number still fails
    uncited = CaseFile(verdict="needs_review", summary="s",
                       claims=[Claim(text="Money went to 87654321.", chunk_ids=["c1"])])
    assert not check_case_file(uncited, facts, {"c1"}).passed     # id rule still applies without facts


def test_triage_baseline():
    f = lambda f7, f9: {"F7": Fact(id="F7", label="", value=f7, source=""),   # noqa: E731
                        "F9": Fact(id="F9", label="", value=f9, source="")}
    assert triage(f(0.6, {"cv": 0.01})) == "likely_legitimate"
    assert triage(f(0.4, {"cv": 0.01})) == "needs_review"
    assert triage(f(None, {"cv": 0.01})) == "needs_review"
    assert triage(f(0.9, None)) == "needs_review"

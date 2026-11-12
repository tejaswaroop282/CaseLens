"""Fan rule, engine and metrics tests (docs/02 section 9). Test-only fixtures."""
import random
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.models import ScenarioParams
from app.rules.engine import ScenarioStateError, make_alert_id, run_scenario
from app.rules.fan import build_pipeline
from app.rules.metrics import compute_metrics
from tests.oracle import run_rule

O = datetime(2022, 9, 1, tzinfo=timezone.utc)
END = O + timedelta(hours=24)
FORMATS = ["ACH", "Wire", "Cash"]
LABEL_KEYS = ("is_laundering", "pattern_type", "pattern_id", "is_suspicious", "n_laundering_tx")


def fixture_rows(seed=42, n=240):
    """A small deterministic fixture: a few hub accounts plus noise, and rows exactly on bucket edges."""
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        hub = rnd.random() < 0.6
        frm = f"H{rnd.randint(0, 2)}" if hub else f"A{rnd.randint(0, 30)}"
        to = f"R{rnd.randint(0, 25)}" if hub else f"H{rnd.randint(0, 2)}"
        rows.append((f"t{i}", O + timedelta(minutes=rnd.randint(0, 24 * 60 - 1)), frm, to, FORMATS[i % 3]))
    for j, h in enumerate((6, 12, 18)):                       # exactly on 6/12-hour bucket boundaries
        rows.append((f"edge{j}", O + timedelta(hours=h), "H0", f"E{j}", "ACH"))
    return pd.DataFrame(rows, columns=["tx_id", "ts", "from_account", "to_account", "payment_format"])


def load(db, df):
    db.stg_transactions.insert_many([
        {**r, "ts": r["ts"].to_pydatetime() if hasattr(r["ts"], "to_pydatetime") else r["ts"],
         "amount_paid": 1.0, "currency_paid": "Euro", "amount_received": 1.0, "currency_received": "Euro"}
        for r in df.to_dict("records")])


def mongo_result(db, direction, p):
    rows = db.stg_transactions.aggregate(build_pipeline(direction, p, O, END), allowDiskUse=True)
    return {(r["account_id"], r["bucket"], r["distinct_counterparties"], r["tx_count"], tuple(sorted(r["tx_ids"])))
            for r in rows}


def oracle_result(df, direction, p):
    if p.payment_formats:
        df = df[df["payment_format"].isin(p.payment_formats)]
    df = df.assign(ts=pd.to_datetime(df["ts"], utc=True))
    r = run_rule(df, direction, p.min_counterparties, p.window_hours, pd.Timestamp(O))
    return {(a, int(b), int(d), int(c), tuple(t)) for a, b, d, c, t in
            r[["account_id", "bucket", "distinct_counterparties", "tx_count", "tx_ids"]].itertuples(index=False)}


@pytest.mark.integration
@pytest.mark.parametrize("window", [1, 5, 6, 12, 24])
def test_mongo_matches_oracle_out(mongo_db, window):
    df = fixture_rows(); load(mongo_db, df)
    p = ScenarioParams(min_counterparties=3, window_hours=window)
    got, want = mongo_result(mongo_db, "out", p), oracle_result(df, "out", p)
    assert got == want and len(got) > 0


@pytest.mark.integration
@pytest.mark.parametrize("window", [1, 6, 24])
def test_mongo_matches_oracle_in(mongo_db, window):
    df = fixture_rows(); load(mongo_db, df)
    p = ScenarioParams(min_counterparties=3, window_hours=window)
    got, want = mongo_result(mongo_db, "in", p), oracle_result(df, "in", p)
    assert got == want and len(got) > 0


@pytest.mark.integration
def test_bucket_edge_belongs_to_next_bucket(mongo_db):
    df = fixture_rows(); load(mongo_db, df)
    p = ScenarioParams(min_counterparties=3, window_hours=6)
    by_bucket = {b: set(t) for a, b, _, _, t in mongo_result(mongo_db, "out", p) if a == "H0"}
    assert "edge0" in by_bucket[1] and "edge0" not in by_bucket.get(0, set())   # 06:00 starts bucket 1


@pytest.mark.integration
def test_repeat_counterparty_counts_once(mongo_db):
    rows = [(f"x{i}", O + timedelta(hours=i), "A", "R1" if i < 4 else f"R{i}", "ACH") for i in range(6)]
    load(mongo_db, pd.DataFrame(rows, columns=["tx_id", "ts", "from_account", "to_account", "payment_format"]))
    assert mongo_result(mongo_db, "out", ScenarioParams(min_counterparties=4, window_hours=24)) == set()
    got = mongo_result(mongo_db, "out", ScenarioParams(min_counterparties=3, window_hours=24))
    assert [(a, d, c) for a, _, d, c, _ in got] == [("A", 3, 6)]


@pytest.mark.integration
def test_payment_format_filter(mongo_db):
    df = fixture_rows(); load(mongo_db, df)
    p = ScenarioParams(min_counterparties=3, window_hours=24, payment_formats=["Wire"])
    got = mongo_result(mongo_db, "out", p)
    assert got == oracle_result(df, "out", p)
    wire = set(df.loc[df["payment_format"] == "Wire", "tx_id"])
    assert got and all(set(t) <= wire for *_, t in got)


# ---------------- metrics (pure) ----------------
def test_pattern_recall_uses_matching_type_only():
    blocks = [{"pattern_type": "fan_out", "tx_ids": ["a", "b"]}, {"pattern_type": "fan_out", "tx_ids": ["z"]},
              {"pattern_type": "fan_in", "tx_ids": ["a"]}]
    m = compute_metrics("out", [["a", "c"], ["d"]], {"a", "b", "z"}, blocks, 24, 0.1)
    assert m["pattern_recall"] == {"caught": 1, "total": 2, "recall": 0.5}
    assert (m["alert_count"], m["suspicious_alert_count"], m["false_alarm_count"]) == (2, 1, 1)
    assert m["alert_precision"] == 0.5 and m["pattern_type"] == "fan_out"
    m_in = compute_metrics("in", [["a"]], {"a"}, blocks, 24, 0.1)
    assert m_in["pattern_recall"] == {"caught": 1, "total": 1, "recall": 1.0}


def test_metrics_null_when_empty():
    m = compute_metrics("out", [], set(), [], 24, 0.0)
    assert m["alert_precision"] is None and m["pattern_recall"]["recall"] is None


def test_alert_id_is_stable():
    a = make_alert_id("s1", "H0", "out", O)
    assert a == make_alert_id("s1", "H0", "out", O) and len(a) == 16 and a != make_alert_id("s1", "H0", "in", O)


# ---------------- engine (Mongo) ----------------
def seed_engine(db, status="approved", min_cp=3, window=24):
    df = fixture_rows(); load(db, df)
    db.pipeline_meta.insert_one({"_id": "meta", "data_origin": O, "slice_end": END, "slice_hours": 24})
    db.stg_labels.insert_many([{"tx_id": "edge0", "is_laundering": True, "pattern_type": "fan_out",
                                "pattern_id": "P1"}])
    db.stg_pattern_blocks.insert_one({"pattern_id": "P1", "pattern_type": "fan_out", "tx_ids": ["edge0"]})
    db.scenarios.insert_one({"scenario_id": "s1", "status": status, "spec": {
        "direction": "out", "params": {"min_counterparties": min_cp, "window_hours": window},
        "legitimate_lookalikes": [], "rationale": "", "unsupported_reason": None}})


@pytest.mark.integration
def test_alerts_have_no_label_field_and_truth_written_for_every_alert(mongo_db):
    seed_engine(mongo_db)
    m = run_scenario(mongo_db, "s1")
    alerts = list(mongo_db.alerts.find({}, {"_id": 0}))
    assert m["alert_count"] == len(alerts) > 0
    assert all(not any(k in a for k in LABEL_KEYS) for a in alerts)
    truth = {t["alert_id"]: t for t in mongo_db.alert_truth.find()}
    assert set(truth) == {a["alert_id"] for a in alerts}
    assert sum(t["is_suspicious"] for t in truth.values()) == m["suspicious_alert_count"] >= 1
    assert mongo_db.scenarios.find_one({"scenario_id": "s1"})["status"] == "completed"
    assert mongo_db.rule_runs.find_one()["status"] == "completed"


@pytest.mark.integration
def test_too_many_alerts_aborts_run(mongo_db):
    seed_engine(mongo_db)
    out = run_scenario(mongo_db, "s1", max_alerts=1)
    assert out["error"]["code"] == "too_many_alerts"
    assert mongo_db.alerts.count_documents({}) == 0
    assert mongo_db.rule_runs.find_one()["status"] == "failed"
    assert mongo_db.scenarios.find_one({"scenario_id": "s1"})["status"] == "failed"


@pytest.mark.integration
def test_scenario_cannot_run_unless_approved(mongo_db):
    seed_engine(mongo_db, status="draft")
    with pytest.raises(ScenarioStateError):
        run_scenario(mongo_db, "s1")
    assert mongo_db.rule_runs.count_documents({}) == 0

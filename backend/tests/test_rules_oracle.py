import pandas as pd
from tests.oracle import run_rule
O = pd.Timestamp("2022-09-01", tz="UTC")
def fx():
    rows = []
    # A sends to 5 different accounts inside bucket 0 (24h window), B sends to 5 but across two buckets
    for i in range(5): rows.append((f"t{i}", O + pd.Timedelta(hours=1+i), "A", f"R{i}", 10.0, "USD"))
    for i in range(3): rows.append((f"u{i}", O + pd.Timedelta(hours=20+i/10), "B", f"S{i}", 5.0, "USD"))
    for i in range(3, 5): rows.append((f"u{i}", O + pd.Timedelta(hours=30+i), "B", f"S{i}", 5.0, "USD"))
    return pd.DataFrame(rows, columns=["tx_id","ts","from_account","to_account","amount_paid","currency_paid"])
def test_fan_out_threshold_and_buckets():
    r = run_rule(fx(), "out", 5, 24, O)
    assert list(r["account_id"]) == ["A"] and r.loc[0, "tx_count"] == 5      # B is split across buckets
def test_fan_in():
    rows = [(f"x{i}", O + pd.Timedelta(hours=i), f"P{i}", "Z", 1.0, "USD") for i in range(6)]
    df = pd.DataFrame(rows, columns=["tx_id","ts","from_account","to_account","amount_paid","currency_paid"])
    r = run_rule(df, "in", 6, 24, O)
    assert list(r["account_id"]) == ["Z"] and r.loc[0, "distinct_counterparties"] == 6
def test_repeat_counterparty_counts_once():
    rows = [(f"x{i}", O + pd.Timedelta(hours=i), "A", "R1" if i < 4 else f"R{i}", 1.0, "USD") for i in range(6)]
    df = pd.DataFrame(rows, columns=["tx_id","ts","from_account","to_account","amount_paid","currency_paid"])
    assert run_rule(df, "out", 4, 24, O).empty          # 6 tx but only 3 distinct receivers

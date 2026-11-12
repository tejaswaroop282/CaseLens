"""Pipeline tests (docs/01 section 8). Tiny hand-made fixtures, test-only (hard rule 1)."""
import io
from datetime import datetime, timedelta, timezone

import pytest

from app.budget import TokenBudgetExceeded, TokenLedger
from pipeline.common import COLS, row_key
from pipeline.ingest_docs import Chunk, chunk_pages, ingest
from pipeline.labels import build_labels
from pipeline.patterns import normalize_type, parse_lines
from pipeline.slice_advice import advise
from pipeline.stage import origin_of, read_chunks, scan, transform_chunk

HEADER = ("Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,Amount Paid,"
          "Payment Currency,Payment Format,Is Laundering")
ROWS = [
    "2022/09/01 00:20,010,8000EBD30,010,8000EBD30,3697.34,US Dollar,3697.34,US Dollar,Reinvestment,0",
    "2022/09/01 01:05,021174,800737690,012,80011F990,2848.96,Euro,2848.96,Euro,ACH,1",
    "2022/09/01 02:00,021174,800737690,013,80022A110,100.00,Euro,100.00,Euro,ACH,1",
    "not a date,010,8000AAAA0,011,8000BBBB0,5.00,US Dollar,5.00,US Dollar,Cash,0",
    "2022/09/01 03:00,010,8000AAAA0,011,8000BBBB0,-5.00,US Dollar,-5.00,US Dollar,Cash,0",
    "2022/09/02 00:10,010,8000CCCC0,011,8000DDDD0,7.00,US Dollar,7.00,US Dollar,Wire,1",
]
O = datetime(2022, 9, 1, tzinfo=timezone.utc)
END24 = O + timedelta(hours=24)


def csv_file(tmp_path, rows=ROWS):
    p = tmp_path / "trans.csv"
    p.write_text(HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return p


def one_chunk(path):
    return next(iter(read_chunks(path)))


def test_two_account_columns_read_by_position(tmp_path):
    ch = one_chunk(csv_file(tmp_path))
    assert list(ch.columns) == COLS
    assert ch.loc[1, "from_account"] == "800737690" and ch.loc[1, "to_account"] == "80011F990"


def test_staging_has_no_label_field(tmp_path):
    res = transform_chunk(one_chunk(csv_file(tmp_path)), 0, END24, bank_account=False)
    assert res.docs and all("is_laundering" not in d for d in res.docs)
    assert res.docs[0]["tx_id"] == "HI-Small-0" and res.docs[0]["ts"] == O + timedelta(minutes=20)
    assert isinstance(res.docs[0]["amount_paid"], float)


def test_timestamp_parse_rejects_bad_rows(tmp_path):
    res = transform_chunk(one_chunk(csv_file(tmp_path)), 0, END24, bank_account=False)
    assert ("HI-Small-3", "bad_timestamp") in res.rejects
    assert ("HI-Small-4", "bad_amount") in res.rejects
    assert len(res.docs) + len(res.rejects) == res.in_slice


def test_slice_keeps_only_first_hours(tmp_path):
    res = transform_chunk(one_chunk(csv_file(tmp_path)), 0, END24, bank_account=False)
    assert all(d["ts"] < END24 for d in res.docs)
    assert res.past_slice == 1 and "HI-Small-5" not in {d["tx_id"] for d in res.docs}
    assert {r["tx_id"] for r in res.label_rows} == {"HI-Small-1", "HI-Small-2"}   # row 5 is outside the slice


def test_account_key_decision_recorded(tmp_path):
    sc = scan(csv_file(tmp_path))
    assert sc.account_key == "account" and sc.earliest == O + timedelta(minutes=20)
    assert origin_of(sc.earliest) == O and sc.bad_ts == 1
    clash = ROWS + ["2022/09/01 04:00,099,8000EBD30,010,8000AAAA0,1.00,US Dollar,1.00,US Dollar,Cash,0"]
    sc2 = scan(csv_file(tmp_path, clash))
    assert sc2.account_key == "bank_account" and sc2.multi_bank_examples[0]["account"] == "8000EBD30"
    res = transform_chunk(one_chunk(csv_file(tmp_path, clash)), 0, END24, bank_account=True)
    assert res.docs[0]["from_account"] == "010|8000EBD30"


def test_scan_detects_unsorted_file(tmp_path):
    rows = [ROWS[2], ROWS[1]]
    assert scan(csv_file(tmp_path, rows)).sorted_by_time is False
    assert scan(csv_file(tmp_path, [ROWS[1], ROWS[2]])).sorted_by_time is True


PATTERNS = f"""BEGIN LAUNDERING ATTEMPT - FAN-OUT
{ROWS[1]}
{ROWS[2]}
END LAUNDERING ATTEMPT - FAN-OUT

BEGIN LAUNDERING ATTEMPT - CYCLE:  Max 10 hops
2022/09/01 05:00,001,800000001,002,800000002,1.00,Euro,1.00,Euro,ACH,1
END LAUNDERING ATTEMPT - CYCLE
BEGIN LAUNDERING ATTEMPT - FAN-IN
{ROWS[5]}
END LAUNDERING ATTEMPT - FAN-IN
"""


def test_patterns_parser_types_and_ids():
    blocks = list(parse_lines(io.StringIO(PATTERNS)))
    assert [(b.pattern_id, b.pattern_type) for b in blocks] == [
        ("HI-Small-P00001", "fan_out"), ("HI-Small-P00002", "cycle"), ("HI-Small-P00003", "fan_in")]
    assert normalize_type("SCATTER-GATHER") == "scatter_gather"
    assert len(blocks[0].lines) == 2 and blocks[0].last_ts == O + timedelta(hours=2)


def test_row_key_matches_pattern_lines(tmp_path):
    res = transform_chunk(one_chunk(csv_file(tmp_path)), 0, END24, bank_account=False)
    blocks = list(parse_lines(io.StringIO(PATTERNS)))
    assert {r["row_key"] for r in res.label_rows} == {ln.key for ln in blocks[0].lines}
    assert row_key(ROWS[1].split(",")[:10]) == blocks[0].lines[0].key


def test_blocks_outside_slice_are_dropped(tmp_path):
    res = transform_chunk(one_chunk(csv_file(tmp_path)), 0, END24, bank_account=False)
    key_to_tx = {}
    for r in res.label_rows:
        key_to_tx.setdefault(r["row_key"], []).append(r["tx_id"])
    out = build_labels(list(parse_lines(io.StringIO(PATTERNS))), key_to_tx, END24)
    assert [b["pattern_id"] for b in out.blocks] == ["HI-Small-P00001"]           # fan_in block is past the slice
    assert out.blocks[0]["tx_ids"] == ["HI-Small-1", "HI-Small-2"]
    assert out.counts["fan_blocks_out_of_slice"] == 1
    assert out.counts["lines_unmatched"] == 1                                       # the cycle line has no tx row
    assert {(l["tx_id"], l["pattern_type"]) for l in out.labels} == {("HI-Small-1", "fan_out"),
                                                                      ("HI-Small-2", "fan_out")}


def test_slice_advice_counts_blocks_inside_window():
    def block(kind, hour):
        return (f"BEGIN LAUNDERING ATTEMPT - {kind}\n"
                f"2022/09/01 {hour:02d}:00,1,A,2,B,1.00,Euro,1.00,Euro,ACH,1\n"
                f"END LAUNDERING ATTEMPT - {kind}\n")
    text = "".join(block("FAN-OUT", h % 24) for h in range(12)) + "".join(block("FAN-IN", 3) for _ in range(10))
    r = advise(list(parse_lines(io.StringIO(text))), hours=(6, 12, 24))
    by_h = {row["hours"]: row for row in r["table"]}
    assert by_h[6] == {"hours": 6, "fan_out": 6, "fan_in": 10}
    assert by_h[12] == {"hours": 12, "fan_out": 12, "fan_in": 10}
    assert r["recommended"] == 12 and r["sufficient"]                  # smallest H with >= 10 of each type


class FakeStore:
    def __init__(self): self.calls = []
    def delete(self, where): self.calls.append(("delete", where))
    def add_texts(self, texts, metadatas, ids): self.calls.append(("add", ids))


def test_chunk_ids_and_metadata():
    doc = {"doc_id": "d1", "title": "T", "url": "https://x", "retrieved_on": "2026-11-12", "file": "d1.pdf"}
    chunks, empty = chunk_pages(doc, ["a " * 600, "", "short page"])
    assert empty == [2]
    assert chunks[0].chunk_id == "c_d1_0001_000" and chunks[-1].chunk_id == "c_d1_0003_000"
    assert chunks[0].metadata == {"doc_id": "d1", "title": "T", "source_url": "https://x", "page": 1,
                                  "chunk_id": "c_d1_0001_000"}


def test_embedding_budget_guard_stops_ingestion():
    store = FakeStore()
    led = TokenLedger(max_input=100, max_output=100, used_input=90)
    chunks = [Chunk("c_d1_0001_000", "x" * 400, {})]                  # ~100 tokens > 10 remaining
    with pytest.raises(TokenBudgetExceeded):
        ingest(store, {"doc_id": "d1"}, chunks, led)
    assert store.calls == []                                           # nothing deleted, nothing embedded
    ok = TokenLedger(max_input=1000, max_output=100)
    ingest(store, {"doc_id": "d1"}, chunks, ok)
    assert store.calls == [("delete", {"doc_id": "d1"}), ("add", ["c_d1_0001_000"])]


@pytest.mark.integration
def test_dq_fails_on_duplicate_tx_id(mongo_db):
    from pipeline.dq import check_staging
    ts = O + timedelta(hours=1)
    doc = {"tx_id": "HI-Small-1", "ts": ts, "from_bank": "1", "from_account": "A", "to_bank": "2", "to_account": "B",
           "amount_paid": 1.0, "currency_paid": "Euro", "amount_received": 1.0, "currency_received": "Euro",
           "payment_format": "ACH"}
    mongo_db.stg_transactions.insert_many([dict(doc), dict(doc)])
    mongo_db.pipeline_meta.insert_one({"_id": "meta", "data_origin": O, "slice_end": END24})
    mongo_db.pipeline_runs.insert_one({"step": "staging", "status": "ok", "finished_at": ts,
                                       "row_counts": {"in_slice": 2, "written": 2, "rejected": 0}})
    checks = {c.name: c for c in check_staging(mongo_db)}
    assert checks["duplicate tx_id"].status == "fail" and checks["duplicate tx_id"].value == 1
    assert checks["stg_transactions has no label field"].status == "pass"

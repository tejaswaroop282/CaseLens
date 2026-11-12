"""M7 / D17 upload and date-range tests. Tiny hand-made CSVs (test-only)."""
import io
from datetime import datetime, timedelta, timezone

import pytest

from app.rules.engine import RangeError, aligned_range, run_scenario
from pipeline import upload as up
from pipeline.stage import read_chunks, transform_chunk

O = datetime(2022, 9, 1, tzinfo=timezone.utc)
HEADER = ("Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,Amount Paid,"
          "Payment Currency,Payment Format,Is Laundering")


def line(ts: datetime, frm="8000AAAA0", to="8000BBBB0", amt="100.00", lab="0", fmt="ACH"):
    return f"{ts:%Y/%m/%d %H:%M},010,{frm},011,{to},{amt},US Dollar,{amt},US Dollar,{fmt},{lab}"


def day_rows(day: int, lab_first=False):
    base = O + timedelta(days=day)
    return [line(base + timedelta(hours=1 + i), to=f"8000R{day}{i:03d}", lab="1" if (lab_first and i == 0) else "0")
            for i in range(6)]


def write(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text(HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return p


def load_base(db, tmp_path):
    """Day 1 loaded as the staging step would (origin 2022-09-01, 24 h slice)."""
    p = write(tmp_path, "day1.csv", day_rows(0))
    res = transform_chunk(next(iter(read_chunks(p))), 0, O + timedelta(hours=24), bank_account=False)
    db.stg_transactions.insert_many(res.docs)
    db.pipeline_meta.insert_one({"_id": "meta", "data_origin": O, "slice_end": O + timedelta(hours=24),
                                 "slice_hours": 24, "account_key": "account"})
    db.scenarios.insert_one({"scenario_id": "s1", "status": "approved", "spec": {
        "direction": "out", "params": {"min_counterparties": 3, "window_hours": 12, "payment_formats": None},
        "legitimate_lookalikes": [], "rationale": "", "unsupported_reason": None}})


def test_aligned_range_snaps_to_whole_windows():
    end = O + timedelta(hours=40)
    assert aligned_range(O, end, 12, None, None) == (O, O + timedelta(hours=36))          # 36-40 h is incomplete
    assert aligned_range(O, end, 12, O + timedelta(hours=5), None) == (O + timedelta(hours=12), O + timedelta(hours=36))
    with pytest.raises(RangeError):
        aligned_range(O, end, 12, O + timedelta(hours=30), O + timedelta(hours=40))


@pytest.mark.integration
def test_validate_report_counts_rejects_and_duplicates(mongo_db, tmp_path):
    load_base(mongo_db, tmp_path)
    rows = day_rows(1, lab_first=True) + [
        "not a date,010,8000X,011,8000Y,1.00,US Dollar,1.00,US Dollar,ACH,0",
        line(O - timedelta(days=1)),                                     # before the data origin
        day_rows(0)[0]]                                                  # already loaded
    rep = up.validate(mongo_db, write(tmp_path, "day2.csv", rows))
    assert rep["ok"] and rep["rows"] == 9 and rep["valid"] == 7 and rep["rejected"] == 2
    assert rep["reasons"] == {"bad_timestamp": 1, "before_data_origin": 1}
    assert rep["already_loaded"] == 1 and rep["to_append"] == 6 and rep["labeled_rows"] == 1
    assert rep["examples"][0] == {"row": 8, "reason": "bad_timestamp"}


@pytest.mark.integration
def test_bad_header_is_rejected(mongo_db, tmp_path):
    load_base(mongo_db, tmp_path)
    p = tmp_path / "x.csv"; p.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    assert up.validate(mongo_db, p)["ok"] is False


@pytest.mark.integration
def test_append_extends_data_and_reupload_adds_nothing(mongo_db, tmp_path):
    load_base(mongo_db, tmp_path)
    p = write(tmp_path, "day2.csv", day_rows(1, lab_first=True) + [day_rows(0)[0]])
    c = up.append(mongo_db, p, "u1", 1)
    assert c["appended"] == 6 and c["already_loaded"] == 1 and c["labels_added"] == 1
    meta = mongo_db.pipeline_meta.find_one({"_id": "meta"})
    assert meta["slice_end"] == O + timedelta(hours=31) and meta["slice_hours"] == 31     # newest tx 30:00 -> 31:00
    assert mongo_db.stg_transactions.count_documents({}) == 12
    assert mongo_db.stg_transactions.count_documents({"is_laundering": {"$exists": True}}) == 0   # no label field
    assert mongo_db.stg_labels.find_one()["pattern_type"] == "other"
    assert mongo_db.stg_transactions.find_one({"upload_id": "u1"})["tx_id"].startswith("UP001-")
    again = up.append(mongo_db, p, "u2", 2)
    assert again["appended"] == 0 and mongo_db.stg_transactions.count_documents({}) == 12


@pytest.mark.integration
def test_genuine_duplicates_inside_a_new_file_are_kept(mongo_db, tmp_path):
    load_base(mongo_db, tmp_path)
    row = line(O + timedelta(hours=26), to="8000DUP00")
    assert up.append(mongo_db, write(tmp_path, "d.csv", [row, row]), "u1", 1)["appended"] == 2
    assert up.append(mongo_db, write(tmp_path, "e.csv", [row, row, row]), "u2", 2)["appended"] == 1


@pytest.mark.integration
def test_new_data_run_creates_only_new_alerts(mongo_db, tmp_path):
    load_base(mongo_db, tmp_path)
    first = run_scenario(mongo_db, "s1")                              # day 1: one alert (06:00 window 0-12 h)
    assert first["alert_count"] == 1 and first["new_alerts"] == 1
    up.append(mongo_db, write(tmp_path, "day2.csv", day_rows(1)), "u1", 1)
    with pytest.raises(RangeError):                                   # data ends 31 h: 24-36 h window not complete
        run_scenario(mongo_db, "s1", mode="new")
    assert mongo_db.scenarios.find_one({"scenario_id": "s1"})["status"] == "completed"   # refused before claiming it
    up.append(mongo_db, write(tmp_path, "day2b.csv", [line(O + timedelta(hours=37), to="8000LATE0")]), "u2", 2)
    m2 = run_scenario(mongo_db, "s1", mode="new")                     # now 24-36 h is complete
    assert m2["new_alerts"] == 1 and mongo_db.alerts.count_documents({}) == 2
    again = run_scenario(mongo_db, "s1", mode="all")                  # everything again: nothing duplicated
    assert again["new_alerts"] == 0 and again["existing_alerts"] == 2 and mongo_db.alerts.count_documents({}) == 2
    assert mongo_db.scenarios.find_one({"scenario_id": "s1"})["status"] == "completed"


@pytest.mark.integration
def test_api_upload_flow_and_range_run(mongo_db, tmp_path):
    from fastapi.testclient import TestClient
    from app.api.common import database
    from app.main import app
    load_base(mongo_db, tmp_path)
    app.dependency_overrides[database] = lambda: mongo_db
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            csv = (HEADER + "\n" + "\n".join(day_rows(1) + [line(O + timedelta(hours=40), to="8000END00")]) + "\n").encode()
            r = c.post("/api/uploads", files={"file": ("day2.csv", io.BytesIO(csv), "text/csv")})
            assert r.status_code == 202, r.text
            uid = r.json()["upload_id"]
            u = c.get(f"/api/uploads/{uid}").json()                    # validation already ran (background task)
            assert u["status"] == "validated" and u["report"]["to_append"] == 7
            assert c.post(f"/api/uploads/{uid}/append").status_code == 202
            assert c.get(f"/api/uploads/{uid}").json()["status"] == "appended"
            assert c.post(f"/api/uploads/{uid}/append").status_code == 409
            # validate on day 2 only: a rule designed on day 1, tested on unseen data
            assert c.post("/api/scenarios/s1/run", json={"mode": "range", "start": "2022-09-02T00:00:00Z",
                                                         "end": "2022-09-03T00:00:00Z"}).status_code == 202
            run = c.get("/api/scenarios/s1").json()["latest_run"]
            assert run["status"] == "completed" and run["range_start"] == "2022-09-02T00:00:00Z"
            assert run["range_end"] == "2022-09-02T12:00:00Z"            # data ends 41:00 -> only 24-36 h complete
            bad = c.post("/api/scenarios/s1/run", json={"mode": "range", "start": "2022-09-02T13:00:00Z",
                                                        "end": "2022-09-02T20:00:00Z"})
            assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_range"
            assert len(c.get("/api/scenarios/s1/runs").json()["items"]) == 1
            dup = c.post("/api/uploads", files={"file": ("again.csv", io.BytesIO(csv), "text/csv")}).json()
            assert c.get(f"/api/uploads/{dup['upload_id']}").json()["status"] == "invalid"   # every row already loaded
            assert c.post("/api/uploads", files={"file": ("x.txt", io.BytesIO(b"x"), "text/plain")}).status_code == 422
    finally:
        app.dependency_overrides.clear()

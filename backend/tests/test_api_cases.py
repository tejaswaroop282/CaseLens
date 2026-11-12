"""Alerts / cases / decisions / mock case system API tests (docs/04 section 5)."""
import json

import pytest

from app import llm, tools
from app.budget import TokenLedger
from tests.fakes import FakeToolChat
from tests.test_investigation import GOOD, FakeStore, scripted, seed

TRUTH = ("is_laundering", "pattern_type", "pattern_id", "is_suspicious", "n_laundering_tx")


@pytest.fixture
def api(mongo_db):
    from fastapi.testclient import TestClient
    from app.api.common import database
    from app.main import app
    seed(mongo_db)
    llm.set_ledgers(chat=TokenLedger(max_input=100_000, max_output=100_000))
    tools.set_store_factory(FakeStore)
    fake = FakeToolChat(replies=[scripted([GOOD])] * 6)
    llm.set_chat_model_factory(lambda *a, **k: fake)
    app.dependency_overrides[database] = lambda: mongo_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, mongo_db
    app.dependency_overrides.clear()
    tools.set_store_factory(None)
    llm.set_chat_model_factory(None)


def investigate(c):
    r = c.post("/api/alerts/a1/investigate")
    assert r.status_code == 202, r.text
    return r.json()["case_id"]                          # TestClient runs the background task before returning


@pytest.mark.integration
def test_alerts_endpoint_has_no_truth_fields(api):
    c, db = api
    db.alerts.update_one({"alert_id": "a1"}, {"$set": {"is_suspicious": True}})   # even if a bug put it there
    lst, one = c.get("/api/alerts?scenario_id=s1").json(), c.get("/api/alerts/a1").json()
    assert lst["total"] == 1 and lst["items"][0]["latest_case"] is None
    assert not any(k in json.dumps([lst, one]) for k in TRUTH)


@pytest.mark.integration
def test_case_endpoint_has_no_truth_fields(api):
    c, _ = api
    case = c.get(f"/api/cases/{investigate(c)}").json()
    assert case["status"] == "checked" and case["alert"]["alert_id"] == "a1"
    assert not any(k in json.dumps(case) for k in TRUTH)
    assert c.get("/api/alerts/a1").json()["latest_case"]["verdict"] == "needs_review"


@pytest.mark.integration
def test_investigate_conflict_when_running(api):
    c, db = api
    db.cases.insert_one({"case_id": "x", "alert_id": "a1", "scenario_id": "s1", "status": "running"})
    r = c.post("/api/alerts/a1/investigate")
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_state"


@pytest.mark.integration
def test_decision_requires_reason_and_valid_state(api):
    c, db = api
    db.cases.insert_one({"case_id": "q", "alert_id": "a1", "scenario_id": "s1", "status": "running"})
    body = {"decision": "dismiss", "reason": "Regular payroll-style payments.", "analyst": "tester"}
    assert c.post("/api/cases/q/decision", json=body).status_code == 409
    db.cases.delete_one({"case_id": "q"})
    cid = investigate(c)
    assert c.post(f"/api/cases/{cid}/decision", json={**body, "reason": "no"}).status_code == 422
    assert c.post(f"/api/cases/{cid}/decision", json={**body, "decision": "approve"}).status_code == 422
    assert c.post(f"/api/cases/{cid}/decision", json={**body, "analyst": ""}).status_code == 422


@pytest.mark.integration
def test_decision_is_append_only_and_updates_statuses(api, monkeypatch):
    c, db = api
    monkeypatch.setattr("app.api.cases.forward_to_case_system", lambda doc: {"ok": True})
    cid = investigate(c)
    body = {"decision": "escalate", "reason": "Many new counterparties in hours.", "analyst": "tester"}
    r = c.post(f"/api/cases/{cid}/decision", json=body)
    assert r.status_code == 201 and r.json()["decision"] == "escalate" and r.json()["ai_verdict"] == "needs_review"
    assert db.cases.find_one({"case_id": cid})["status"] == "decided"
    assert db.alerts.find_one({"alert_id": "a1"})["status"] == "reviewed"
    assert c.post(f"/api/cases/{cid}/decision", json=body).status_code == 409    # no second decision on a case
    assert db.decisions.count_documents({"case_id": cid}) == 1
    assert c.get(f"/api/cases/{cid}").json()["decision"]["decision"] == "escalate"
    assert c.get("/api/decisions/summary").json() == {"dismiss": 0, "escalate": 1, "need_info": 0}


@pytest.mark.integration
def test_decision_forwarded_to_mock_system_and_failure_does_not_block(api, monkeypatch):
    c, db = api
    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: c.post(url.split("8000", 1)[1], json=json))
    cid = investigate(c)
    r = c.post(f"/api/cases/{cid}/decision", json={"decision": "dismiss", "reason": "Payroll pattern.", "analyst": "t"})
    ack = r.json()["mock_case_system"]
    assert r.status_code == 201 and ack["ok"] and ack["external_id"].startswith("EXT-")
    assert c.get("/api/mock-case-system/cases").json()["items"][0]["case_id"] == cid

    def boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx, "post", boom)
    db.alerts.update_one({"alert_id": "a1"}, {"$set": {"status": "new"}})
    cid2 = investigate(c)
    r2 = c.post(f"/api/cases/{cid2}/decision", json={"decision": "need_info", "reason": "Need KYC.", "analyst": "t"})
    assert r2.status_code == 201 and r2.json()["mock_case_system"] == {"ok": False, "error": "ConnectError"}
    assert db.cases.find_one({"case_id": cid2})["status"] == "decided"

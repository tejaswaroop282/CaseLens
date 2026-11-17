"""Sign-in and role checks (D19). No MongoDB: role checks run before any database query."""
import time

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app


@pytest.fixture()
def client():
    app.dependency_overrides.clear()
    return TestClient(app, raise_server_exceptions=False)       # no `with`: lifespan (Mongo) not started


def _login(c, username, password):
    return c.post("/api/auth/login", json={"username": username, "password": password})


def test_demo_accounts_sign_in_with_their_roles(client):
    r = _login(client, "meera", "owner123")
    assert r.status_code == 200 and r.json()["user"]["role"] == "owner"
    r = _login(client, "Ravi ", "analyst123")                    # username is trimmed and case-insensitive
    assert r.status_code == 200 and r.json()["user"] == {"username": "ravi", "name": "Ravi", "role": "analyst",
                                                         "role_label": "Analyst"}
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['token']}"})
    assert me.json()["username"] == "ravi"


@pytest.mark.parametrize("u,p", [("meera", "wrong"), ("nobody", "owner123"), ("ravi", "owner123")])
def test_wrong_credentials_are_rejected(client, u, p):
    r = _login(client, u, p)
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


def test_tampered_and_expired_tokens_are_rejected():
    user = auth.User("ravi", "Ravi", frozenset({"analyst"}))
    tok = auth.issue_token(user)
    assert auth.read_token(tok).username == "ravi"
    body, sig = tok.split(".")
    forged = auth._b64(b'{"sub":"meera","exp":9999999999}') + "." + sig     # try to become the owner
    with pytest.raises(auth.Unauthorized):
        auth.read_token(forged)
    with pytest.raises(auth.Unauthorized):
        auth.read_token(tok, now=time.time() + 9 * 3600)                     # past AUTH_TOKEN_HOURS (8)
    with pytest.raises(auth.Unauthorized):
        auth.read_token("garbage")


def test_protected_endpoints_need_a_session(client):
    assert client.get("/api/scenarios").status_code == 401
    assert client.post("/api/scenarios/parse", json={"intent_text": "x"}).status_code == 401
    assert client.get("/api/health").status_code == 200                      # health stays public


def test_roles_are_enforced_on_the_server(client):
    owner = {"Authorization": f"Bearer {_login(client, 'meera', 'owner123').json()['token']}"}
    analyst = {"Authorization": f"Bearer {_login(client, 'ravi', 'analyst123').json()['token']}"}
    # analyst cannot change rules or data
    for path in ("/api/scenarios/parse", "/api/scenarios/x/approve", "/api/scenarios/x/run", "/api/scenarios/x/clone",
                 "/api/scenarios/run-new-data", "/api/uploads/x/append"):
        r = client.post(path, json={"intent_text": "x"}, headers=analyst)
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden", path
    # owner cannot investigate or decide cases
    assert client.post("/api/alerts/x/investigate", headers=owner).status_code == 403
    r = client.post("/api/cases/x/decision", json={"decision": "dismiss", "reason": "fine"}, headers=owner)
    assert r.status_code == 403

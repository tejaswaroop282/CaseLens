"""Sign-in with two roles and predefined demo accounts (decision D19).

Roles:
- owner   (risk owner): Scenario Studio (parse, edit, approve, run) and Data uploads.
- analyst:              investigate alerts and record case decisions.
Both roles can read scenarios, alerts and cases.

Tokens are HMAC-SHA256 signed (stdlib only), carry the user and role, and expire after AUTH_TOKEN_HOURS.
Passwords are stored only as PBKDF2 hashes. This is demo-grade sign-in for a prototype, not production
identity management (no user admin, no password change, no lockout)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional

from fastapi import Depends, Header

from app.config import get_settings
from app.errors import AppError
from app.logging import get_logger

log = get_logger("auth")

ROLE_LABELS = {"owner": "Risk owner", "analyst": "Analyst"}

# Predefined demo accounts. The passwords are shown on the sign-in page on purpose (prototype).
DEMO_ACCOUNTS: dict[str, dict] = {
    "meera": {"name": "Meera", "role": "owner", "salt": "ed13de9a9274408a",
              "hash": "a6869c5fa8e0440278b1a5ac6353271c01012e15ec6339255caebf3cc9b79d57"},
    "ravi": {"name": "Ravi", "role": "analyst", "salt": "0365be281f8095ee",
             "hash": "291405fd0b5f13a8eec6f0f11d826a91edbaff699c27c048ff9b2c85c2047969"},
}
PBKDF2_ROUNDS = 200_000


class Unauthorized(AppError):
    status, code = 401, "unauthorized"


class Forbidden(AppError):
    status, code = 403, "forbidden"


@dataclass(frozen=True)
class User:
    username: str
    name: str
    roles: frozenset = field(default_factory=frozenset)

    @property
    def role(self) -> str:
        return next(iter(sorted(self.roles)), "")

    def public(self) -> dict:
        return {"username": self.username, "name": self.name, "role": self.role,
                "role_label": ROLE_LABELS.get(self.role, self.role)}


_ephemeral_secret: Optional[bytes] = None


def _secret() -> bytes:
    global _ephemeral_secret
    s = get_settings().auth_secret
    if s:
        return s.encode()
    if _ephemeral_secret is None:            # no AUTH_SECRET: sessions end when the server restarts
        _ephemeral_secret = secrets.token_bytes(32)
        log.warning("auth_secret_missing", note="set AUTH_SECRET in .env to keep sessions across restarts")
    return _ephemeral_secret


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def check_password(username: str, password: str) -> Optional[User]:
    acc = DEMO_ACCOUNTS.get((username or "").strip().lower())
    if not acc:
        hashlib.pbkdf2_hmac("sha256", password.encode(), b"0" * 8, PBKDF2_ROUNDS)    # same cost either way
        return None
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(acc["salt"]), PBKDF2_ROUNDS).hex()
    if not hmac.compare_digest(h, acc["hash"]):
        return None
    return User(username.strip().lower(), acc["name"], frozenset({acc["role"]}))


def issue_token(user: User, now: Optional[float] = None) -> str:
    exp = int((now or time.time()) + get_settings().auth_token_hours * 3600)
    body = _b64(json.dumps({"sub": user.username, "exp": exp}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str, now: Optional[float] = None) -> User:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        raise Unauthorized("Invalid session. Please sign in again.")
    good = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, good):
        raise Unauthorized("Invalid session. Please sign in again.")
    data = json.loads(_unb64(body))
    if data.get("exp", 0) < (now or time.time()):
        raise Unauthorized("Your session has expired. Please sign in again.")
    acc = DEMO_ACCOUNTS.get(data.get("sub", ""))
    if not acc:
        raise Unauthorized("Unknown user. Please sign in again.")
    return User(data["sub"], acc["name"], frozenset({acc["role"]}))


def current_user(authorization: Optional[str] = Header(default=None)) -> User:
    """FastAPI dependency. Tests override it with a user that has both roles."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Please sign in.")
    return read_token(authorization.split(" ", 1)[1].strip())


def require_role(role: str):
    def dep(user: User = Depends(current_user)) -> User:
        if role not in user.roles:
            raise Forbidden(f"This action needs the {ROLE_LABELS.get(role, role)} role.")
        return user
    return dep


require_owner = require_role("owner")
require_analyst = require_role("analyst")

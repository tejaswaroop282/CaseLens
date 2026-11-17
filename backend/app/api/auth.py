"""Sign-in endpoints (D19)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import Unauthorized, User, check_password, current_user, issue_token

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


@router.post("/login")
def login(body: LoginBody) -> dict:
    user = check_password(body.username, body.password)
    if user is None:
        raise Unauthorized("Wrong username or password.")
    return {"token": issue_token(user), "user": user.public()}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return user.public()

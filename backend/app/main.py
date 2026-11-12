"""FastAPI app: routers, CORS, request-id middleware, error contract."""
from __future__ import annotations

import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import health
from app.llm import apply_langsmith_env
from app.logging import get_logger

log = get_logger("api")
apply_langsmith_env()

app = FastAPI(title="CaseLens", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


def error_body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


@app.middleware("http")
async def request_id(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    structlog.contextvars.bind_contextvars(request_id=rid)
    try:
        response = await call_next(request)
    finally:
        structlog.contextvars.unbind_contextvars("request_id")
    response.headers["X-Request-ID"] = rid
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    code = {400: "bad_request", 404: "not_found", 409: "invalid_state"}.get(exc.status_code, "error")
    return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(error_body("validation_error", "invalid request", {"errors": exc.errors()}), status_code=422)


@app.exception_handler(Exception)
async def internal_error(request: Request, exc: Exception):
    log.error("unhandled_error", error=type(exc).__name__)
    return JSONResponse(error_body("internal_error", "internal error"), status_code=500)


app.include_router(health.router, prefix="/api")

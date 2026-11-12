"""FastAPI app: routers, CORS, request-id middleware, error contract, startup recovery."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import health, scenarios
from app.budget import TokenBudgetExceeded
from app.errors import AppError
from app.llm import apply_langsmith_env
from app.logging import get_logger
from app.scenario.parse import ScenarioParseError

log = get_logger("api")
apply_langsmith_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app import db
    if db.ping():
        db.ensure_indexes()
        from app.api.common import recover_interrupted
        log.info("startup_recovery", **recover_interrupted(db.get_db()))
    else:
        log.warning("startup_mongo_unreachable")
    yield


app = FastAPI(title="CaseLens", version="0.1.0", lifespan=lifespan)
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


@app.exception_handler(AppError)
async def app_error(request: Request, exc: AppError):
    return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status)


@app.exception_handler(TokenBudgetExceeded)
async def budget_error(request: Request, exc: TokenBudgetExceeded):
    log.warning("llm_budget_exhausted")
    return JSONResponse(error_body("llm_budget_exhausted", "the AI token budget is used up", {}), status_code=402)


@app.exception_handler(ScenarioParseError)
async def parse_error(request: Request, exc: ScenarioParseError):
    return JSONResponse(error_body("parse_failed", "the AI could not produce a valid scenario; try rewording",
                                   {}), status_code=502)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    code = {400: "bad_request", 404: "not_found", 405: "bad_request", 409: "invalid_state"}.get(exc.status_code, "error")
    return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    errs = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
    return JSONResponse(error_body("validation_error", "invalid request", {"errors": errs}), status_code=422)


@app.exception_handler(Exception)
async def internal_error(request: Request, exc: Exception):
    try:
        from botocore.exceptions import BotoCoreError, ClientError
        if isinstance(exc, (BotoCoreError, ClientError)):
            log.error("llm_unavailable", error=type(exc).__name__)
            return JSONResponse(error_body("llm_unavailable", "the AI service is unavailable"), status_code=502)
    except ImportError:
        pass
    log.error("unhandled_error", error=type(exc).__name__)
    return JSONResponse(error_body("internal_error", "internal error"), status_code=500)


app.include_router(health.router, prefix="/api")
app.include_router(scenarios.router, prefix="/api")

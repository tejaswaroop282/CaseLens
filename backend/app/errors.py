"""Application errors mapped to the API error contract {"error": {"code", "message", "details"}}."""
from __future__ import annotations

from typing import Optional


class AppError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str, details: Optional[dict] = None, code: Optional[str] = None,
                 status: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code:
            self.code = code
        if status:
            self.status = status


class NotFound(AppError):
    status, code = 404, "not_found"


class InvalidState(AppError):
    status, code = 409, "invalid_state"


class ValidationFailed(AppError):
    status, code = 422, "validation_error"


class ParseFailed(AppError):
    status, code = 502, "parse_failed"


class LlmUnavailable(AppError):
    status, code = 502, "llm_unavailable"


class BudgetExhausted(AppError):
    status, code = 402, "llm_budget_exhausted"

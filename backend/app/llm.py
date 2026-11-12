"""Model factories and the shared token ledgers.

Every chat call carries a BudgetCallback on the shared chat ledger; every embedding call goes through
BudgetedEmbeddings on the embedding ledger. Ledgers start from the totals already stored in `llm_usage`,
so the budget is cumulative across restarts. If the usage store cannot be read, no ledger is created
and therefore no paid call can be made (fail closed).

Tests override the factories with set_chat_model_factory / set_embeddings_factory (no network)."""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from langchain_core.embeddings import Embeddings

from app.budget import BudgetCallback, TokenBudgetExceeded, TokenLedger
from app.config import get_settings
from app.logging import get_logger

log = get_logger("llm")

_lock = threading.Lock()
_chat_factory: Optional[Callable[..., Any]] = None
_embed_factory: Optional[Callable[..., Embeddings]] = None
_chat_ledger: Optional[TokenLedger] = None
_embed_ledger: Optional[TokenLedger] = None


# ---------- LangSmith ----------
def apply_langsmith_env() -> None:
    """LangChain reads tracing settings from os.environ; copy them from config (never print the key)."""
    s = get_settings()
    os.environ["LANGSMITH_TRACING"] = "true" if (s.langsmith_tracing and s.langsmith_api_key) else "false"
    os.environ["LANGSMITH_PROJECT"] = s.langsmith_project
    if s.langsmith_api_key:
        os.environ["LANGSMITH_API_KEY"] = s.langsmith_api_key


# ---------- ledgers ----------
def _usage_collection():
    from app.db import get_db
    return get_db().llm_usage


def _persist(kind: str) -> Callable[[dict], None]:
    model_id = get_settings().bedrock_llm_id if kind == "llm" else get_settings().bedrock_embed_id

    def write(doc: dict) -> None:
        try:
            _usage_collection().insert_one({"kind": kind, "model_id": model_id,
                                            "ts": datetime.now(timezone.utc), **doc})
        except Exception as e:     # the in-memory ledger still counts; the record is lost
            log.warning("llm_usage_persist_failed", kind=kind, error=type(e).__name__)
    return write


def _totals(kind: str) -> tuple[int, int, int]:
    rows = list(_usage_collection().aggregate([
        {"$match": {"kind": kind}},
        {"$group": {"_id": None, "i": {"$sum": "$input_tokens"}, "o": {"$sum": "$output_tokens"}, "n": {"$sum": 1}}},
    ]))
    return (rows[0]["i"], rows[0]["o"], rows[0]["n"]) if rows else (0, 0, 0)


def _load_ledger(kind: str, max_in: int, max_out: int) -> TokenLedger:
    try:
        used_in, used_out, calls = _totals(kind)
    except Exception as e:
        raise RuntimeError("Cannot read llm_usage from MongoDB, so the token budget cannot be enforced. "
                           "Start MongoDB (docker compose up -d mongo) before making AI calls.") from e
    return TokenLedger(max_input=max_in, max_output=max_out, used_input=used_in, used_output=used_out,
                       calls=calls, persist=_persist(kind))


def get_chat_ledger() -> TokenLedger:
    global _chat_ledger
    with _lock:
        if _chat_ledger is None:
            s = get_settings()
            _chat_ledger = _load_ledger("llm", s.llm_token_budget_input, s.llm_token_budget_output)
        return _chat_ledger


def get_embed_ledger() -> TokenLedger:
    global _embed_ledger
    with _lock:
        if _embed_ledger is None:
            s = get_settings()
            # embeddings only consume input tokens; max_output is never reached
            _embed_ledger = _load_ledger("embed", s.embed_token_budget, s.embed_token_budget)
        return _embed_ledger


def set_ledgers(chat: Optional[TokenLedger] = None, embed: Optional[TokenLedger] = None) -> None:
    """For tests and scripts: install ledgers explicitly."""
    global _chat_ledger, _embed_ledger
    with _lock:
        if chat is not None:
            _chat_ledger = chat
        if embed is not None:
            _embed_ledger = embed


def budget_callback(meta: Optional[dict] = None) -> BudgetCallback:
    return BudgetCallback(get_chat_ledger(), meta or {})


# ---------- chat model ----------
def _default_chat_model(max_tokens: Optional[int] = None):
    from botocore.config import Config
    from langchain_aws import ChatBedrockConverse

    s = get_settings()
    if not s.bedrock_llm_id:
        raise RuntimeError("BEDROCK_LLM_ID is not set in .env")
    apply_langsmith_env()
    kwargs: dict[str, Any] = dict(
        model=s.bedrock_llm_id,
        region_name=s.aws_region,
        temperature=s.llm_temperature,
        max_tokens=max_tokens or s.llm_max_tokens,
        config=Config(retries={"max_attempts": 5, "mode": "adaptive"}, read_timeout=60),
    )
    if s.aws_profile:
        kwargs["credentials_profile_name"] = s.aws_profile
    if s.llm_extra_request_fields:
        kwargs["additional_model_request_fields"] = s.llm_extra_request_fields
    return ChatBedrockConverse(**kwargs)


def get_chat_model(role: str = "default", **kw):
    return (_chat_factory or _default_chat_model)(**kw)


def set_chat_model_factory(factory: Optional[Callable[..., Any]]) -> None:
    global _chat_factory
    _chat_factory = factory


# ---------- embeddings ----------
class BudgetedEmbeddings(Embeddings):
    """Wraps any Embeddings. Estimates tokens as characters / 4, refuses a call that would exceed the
    embedding budget, and records usage after the call."""

    def __init__(self, inner: Embeddings, ledger: TokenLedger, meta: Optional[dict] = None):
        self.inner, self.ledger, self.meta = inner, ledger, meta or {}

    @staticmethod
    def estimate(texts: list[str]) -> int:
        return max(1, sum(len(t) for t in texts) // 4)

    def _guard(self, est: int) -> None:
        if self.ledger.used_input + est > self.ledger.max_input:
            raise TokenBudgetExceeded(
                f"embedding budget would be exceeded: used {self.ledger.used_input} + {est} > {self.ledger.max_input}")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        est = self.estimate(texts); self._guard(est)
        out = self.inner.embed_documents(texts)
        self.ledger.add(est, 0, {**self.meta, "n_texts": len(texts), "estimated": True})
        return out

    def embed_query(self, text: str) -> list[float]:
        est = self.estimate([text]); self._guard(est)
        out = self.inner.embed_query(text)
        self.ledger.add(est, 0, {**self.meta, "n_texts": 1, "estimated": True})
        return out


def _default_embeddings() -> Embeddings:
    from langchain_aws import BedrockEmbeddings

    s = get_settings()
    kwargs: dict[str, Any] = dict(model_id=s.bedrock_embed_id, region_name=s.aws_region,
                                  model_kwargs={"dimensions": s.embed_dimensions, "normalize": True})
    if s.aws_profile:
        kwargs["credentials_profile_name"] = s.aws_profile
    return BedrockEmbeddings(**kwargs)


def get_embeddings(meta: Optional[dict] = None) -> Embeddings:
    inner = (_embed_factory or _default_embeddings)()
    return BudgetedEmbeddings(inner, get_embed_ledger(), meta)


def set_embeddings_factory(factory: Optional[Callable[..., Embeddings]]) -> None:
    global _embed_factory
    _embed_factory = factory

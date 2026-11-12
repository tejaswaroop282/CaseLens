"""Cost-control tests for app.llm (no network, no MongoDB)."""
import pytest
from langchain_core.embeddings import FakeEmbeddings

from app import llm
from app.budget import TokenBudgetExceeded, TokenLedger


def test_embedding_guard_records_and_stops():
    seen = []
    led = TokenLedger(max_input=30, max_output=30, persist=seen.append)
    emb = llm.BudgetedEmbeddings(FakeEmbeddings(size=8), led, {"node": "t"})
    assert len(emb.embed_query("x" * 40)) == 8          # 10 estimated tokens
    assert led.used_input == 10 and seen[0]["node"] == "t"
    with pytest.raises(TokenBudgetExceeded):
        emb.embed_documents(["y" * 100])                  # 25 more would exceed 30
    assert led.used_input == 10                           # refused call is not counted and not sent


def test_ledger_fails_closed_without_usage_store(monkeypatch):
    def broken():
        raise ConnectionError("mongo down")
    monkeypatch.setattr(llm, "_usage_collection", broken)
    with pytest.raises(RuntimeError, match="token budget cannot be enforced"):
        llm._load_ledger("llm", 100, 100)


def test_ledger_starts_from_stored_totals(monkeypatch):
    monkeypatch.setattr(llm, "_totals", lambda kind: (90, 5, 3))
    monkeypatch.setattr(llm, "_persist", lambda kind: None)
    led = llm._load_ledger("llm", 100, 100)
    assert (led.used_input, led.used_output, led.calls) == (90, 5, 3)
    assert led.remaining() == {"input": 10, "output": 95}

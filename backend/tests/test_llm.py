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


def test_normalized_embeddings_are_unit_length():
    class Fixed(FakeEmbeddings):
        def embed_documents(self, texts):
            return [[3.0, 4.0] for _ in texts]

        def embed_query(self, text):
            return [0.0, 0.0]
    e = llm.NormalizedEmbeddings(Fixed(size=2))
    assert e.embed_documents(["a"]) == [[0.6, 0.8]]
    assert e.embed_query("q") == [0.0, 0.0]                # zero vector left as is


def _settings(monkeypatch, **env):
    from app import config
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()
    monkeypatch.setattr(llm, "_rate_limiter", None)


def test_gemini_provider_builds_gemini_models(monkeypatch):
    _settings(monkeypatch, LLM_PROVIDER="gemini", GEMINI_API_KEY="test-not-a-real-key", GEMINI_THINKING_BUDGET="0",
              LLM_REQUESTS_PER_MINUTE="8", LANGSMITH_TRACING="false")
    try:
        chat = llm._default_chat_model()
        assert type(chat).__name__ == "ChatGoogleGenerativeAI"
        assert chat.temperature == 0 and chat.max_output_tokens == 1000 and chat.rate_limiter is not None
        emb = llm._default_embeddings()
        assert isinstance(emb, llm.NormalizedEmbeddings) and emb.inner.output_dimensionality == 512
    finally:
        from app import config
        config.get_settings.cache_clear()


def test_gemini_provider_requires_key(monkeypatch):
    _settings(monkeypatch, LLM_PROVIDER="gemini", GEMINI_API_KEY="")
    try:
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            llm._default_chat_model()
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            llm._default_embeddings()
    finally:
        from app import config
        config.get_settings.cache_clear()

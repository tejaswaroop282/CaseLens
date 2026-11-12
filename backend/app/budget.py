"""Token budget guard for Bedrock calls (keeps the project inside a small free-credit budget).

Use one TokenLedger per process. Attach BudgetCallback to every LLM call via config={"callbacks": [cb]}.
Calls are refused once the budget is used up. Usage is read from the model response (usage_metadata)."""
from __future__ import annotations
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from langchain_core.callbacks import BaseCallbackHandler

class TokenBudgetExceeded(RuntimeError):
    pass

@dataclass
class TokenLedger:
    max_input: int
    max_output: int
    used_input: int = 0
    used_output: int = 0
    calls: int = 0
    persist: Optional[Callable[[dict], None]] = None     # e.g. insert a document into Mongo `llm_usage`
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def exceeded(self) -> bool:
        return self.used_input >= self.max_input or self.used_output >= self.max_output

    def add(self, input_tokens: int, output_tokens: int, meta: Optional[dict] = None) -> None:
        with self._lock:
            self.used_input += int(input_tokens); self.used_output += int(output_tokens); self.calls += 1
        if self.persist:
            self.persist({"input_tokens": int(input_tokens), "output_tokens": int(output_tokens), **(meta or {})})

    def remaining(self) -> dict:
        return {"input": max(self.max_input - self.used_input, 0), "output": max(self.max_output - self.used_output, 0)}

class BudgetCallback(BaseCallbackHandler):
    raise_error = True          # exceptions raised here stop the call instead of being swallowed

    def __init__(self, ledger: TokenLedger, meta: Optional[dict] = None):
        self.ledger = ledger; self.meta = meta or {}

    def _check(self) -> None:
        if self.ledger.exceeded():
            raise TokenBudgetExceeded(f"token budget used up: {self.ledger.used_input} in / {self.ledger.used_output} out")

    def on_chat_model_start(self, serialized: Any, messages: Any, **kwargs: Any) -> None: self._check()
    def on_llm_start(self, serialized: Any, prompts: Any, **kwargs: Any) -> None: self._check()

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        tin = tout = 0
        for gens in response.generations:
            for g in gens:
                um = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
                tin += um.get("input_tokens", 0); tout += um.get("output_tokens", 0)
        self.ledger.add(tin, tout, self.meta)

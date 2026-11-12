"""Test doubles for the LLM (no network). Responses go through the real LangChain callback and
structured-output machinery, so the token budget callback and parsers are exercised for real."""
from __future__ import annotations

from typing import Any, Callable, Optional, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, PrivateAttr

Reply = Union[BaseModel, dict, Callable[[list[BaseMessage]], Union[BaseModel, dict]]]


class FakeToolChat(BaseChatModel):
    """Each call pops the next reply and returns it as a tool call (what with_structured_output parses).
    A reply may be a model instance, a raw args dict (to simulate invalid output), or a callable of the
    prompt messages. Every prompt is recorded in .prompts (used by leakage tests)."""

    replies: list = []
    tool_name: str = "ScenarioSpec"
    input_tokens: int = 100
    output_tokens: int = 20
    _prompts: list = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake-tool-chat"

    @property
    def prompts(self) -> list[str]:
        return self._prompts

    def bind_tools(self, tools: Any, **kwargs: Any):
        return self

    def _generate(self, messages: list[BaseMessage], stop: Optional[list[str]] = None, run_manager=None,
                  **kwargs: Any) -> ChatResult:
        self._prompts.append("\n".join(str(m.content) for m in messages))
        if not self.replies:
            raise AssertionError("FakeToolChat: no replies left (too many LLM calls)")
        r = self.replies.pop(0)
        if callable(r) and not isinstance(r, BaseModel):
            r = r(messages)
        args = r.model_dump() if isinstance(r, BaseModel) else r
        name = type(r).__name__ if isinstance(r, BaseModel) else self.tool_name
        msg = AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{len(self._prompts)}"}],
                        usage_metadata={"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                                        "total_tokens": self.input_tokens + self.output_tokens})
        return ChatResult(generations=[ChatGeneration(message=msg)])


def install_fake_llm(replies: list, **kw) -> FakeToolChat:
    """Make app.llm.get_chat_model return one shared fake; returns it for inspection."""
    from app import llm
    fake = FakeToolChat(replies=list(replies), **kw)
    llm.set_chat_model_factory(lambda *a, **k: fake)
    return fake

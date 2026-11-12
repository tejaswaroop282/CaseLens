"""The LLM's only job in Scenario Studio: fill ScenarioSpec. The worry text goes in the human message only."""
from __future__ import annotations

from typing import Optional

from langchain_core.exceptions import OutputParserException
from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError

from app.config import get_settings
from app.llm import budget_callback, get_chat_model
from app.models import ScenarioSpec
from app.scenario.prompts import SYSTEM_PROMPT

MAX_INTENT_CHARS = 1000


class ScenarioParseError(Exception):
    pass


def parse_intent(intent_text: str, formats: list[str], max_window_hours: int,
                 callbacks: Optional[list] = None, metadata: Optional[dict] = None) -> ScenarioSpec:
    """Two attempts (one retry) on parse/validation failure. TokenBudgetExceeded is never retried."""
    s = get_settings()
    llm = get_chat_model("scenario_parse").with_structured_output(ScenarioSpec)
    chain = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", "{intent}")]) | llm
    callbacks = callbacks if callbacks is not None else [budget_callback({"node": "scenario_parse"})]
    config = {"callbacks": callbacks, "tags": ["caselens", "scenario_parse"],
              "metadata": {"prompt_version": s.prompt_version, **(metadata or {})}}
    inputs = {"intent": intent_text.strip(), "formats": ", ".join(formats) or "(none)",
              "max_window": max_window_hours}
    last: Optional[Exception] = None
    for _ in range(2):
        try:
            out = chain.invoke(inputs, config=config)
            if out is None:                       # model answered without filling the schema
                raise OutputParserException("model returned no structured output")
            return out
        except (OutputParserException, ValidationError) as e:
            last = e
    raise ScenarioParseError(f"{type(last).__name__}: {str(last)[:300]}")

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from budget import TokenLedger, BudgetCallback, TokenBudgetExceeded

def msgs(n, tin=100, tout=20):
    return iter([AIMessage(content=f"ok{i}", usage_metadata={"input_tokens": tin, "output_tokens": tout, "total_tokens": tin + tout}) for i in range(n)])

def test_usage_is_recorded():
    led = TokenLedger(max_input=1000, max_output=1000)
    GenericFakeChatModel(messages=msgs(2)).invoke("hi", config={"callbacks": [BudgetCallback(led)]})
    assert (led.used_input, led.used_output, led.calls) == (100, 20, 1)

def test_budget_blocks_next_call():
    led = TokenLedger(max_input=150, max_output=1000)
    llm = GenericFakeChatModel(messages=msgs(5)); cb = BudgetCallback(led)
    llm.invoke("a", config={"callbacks": [cb]}); llm.invoke("b", config={"callbacks": [cb]})   # 200 in >= 150
    with pytest.raises(TokenBudgetExceeded): llm.invoke("c", config={"callbacks": [cb]})
    assert led.calls == 2

def test_persist_hook_called_with_meta():
    seen = []
    led = TokenLedger(max_input=1000, max_output=1000, persist=seen.append)
    GenericFakeChatModel(messages=msgs(1)).invoke("x", config={"callbacks": [BudgetCallback(led, {"node": "drafter"})]})
    assert seen == [{"input_tokens": 100, "output_tokens": 20, "node": "drafter"}]

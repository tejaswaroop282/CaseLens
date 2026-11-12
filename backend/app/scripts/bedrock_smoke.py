"""M0 smoke test: one chat reply, one structured output, one embedding, with token usage.

All calls go through the token ledger (stored in Mongo `llm_usage`), so MongoDB must be running.
Total cost is a few hundred tokens. Never prints credentials.

    python -m app.scripts.bedrock_smoke
"""
from __future__ import annotations

import json
import sys
import time

from app.config import get_settings
from app.llm import budget_callback, get_chat_ledger, get_embed_ledger, get_chat_model, get_embeddings
from app.models import ScenarioSpec


def _content_summary(msg) -> tuple[str, list[str]]:
    """Return (answer text, block types). Reasoning models may return a list of content blocks."""
    if isinstance(msg.content, str):
        return msg.content, ["text"]
    texts, kinds = [], []
    for b in msg.content:
        kind = b.get("type", "?") if isinstance(b, dict) else type(b).__name__
        kinds.append(kind)
        if isinstance(b, dict) and kind == "text":
            texts.append(b.get("text", ""))
    return "".join(texts), kinds


def main() -> int:
    s = get_settings()
    print(f"region={s.aws_region} profile={s.aws_profile or '(default chain)'} "
          f"llm={s.bedrock_llm_id} embed={s.bedrock_embed_id} dims={s.embed_dimensions} max_tokens={s.llm_max_tokens}")
    if not s.bedrock_llm_id:
        print("FAIL: BEDROCK_LLM_ID is empty in .env"); return 1
    led = get_chat_ledger()
    print(f"chat ledger before: used in={led.used_input} out={led.used_output} calls={led.calls}")

    ok = True
    # 1. plain chat reply
    t = time.time()
    msg = get_chat_model().invoke("Reply with exactly one word: ok",
                                  config={"callbacks": [budget_callback({"node": "smoke_chat"})],
                                          "tags": ["caselens", "smoke"]})
    text, kinds = _content_summary(msg)
    print(f"[1] chat reply: {text.strip()!r}  blocks={kinds}  {time.time() - t:.1f}s")
    print(f"    usage_metadata: {json.dumps(msg.usage_metadata)}")
    if not msg.usage_metadata or not msg.usage_metadata.get("input_tokens"):
        print("    WARN: no usage metadata; the ledger cannot count this model's tokens"); ok = False

    # 2. structured output (tool use through Converse) -- every LLM node depends on this
    t = time.time()
    try:
        spec = get_chat_model().with_structured_output(ScenarioSpec).invoke(
            "Convert this worry into the schema. Fan pattern only; direction 'in' means one account receives "
            "from many different accounts. Worry: Flag accounts that receive money from at least 20 different "
            "accounts within 12 hours.",
            config={"callbacks": [budget_callback({"node": "smoke_structured"})], "tags": ["caselens", "smoke"]})
        print(f"[2] structured output: {spec.model_dump_json()}  {time.time() - t:.1f}s")
        if spec.direction != "in" or not spec.params or spec.params.min_counterparties != 20:
            print("    WARN: parsed, but values differ from the expected direction=in, N=20, W=12")
    except Exception as e:
        print(f"[2] FAIL structured output: {type(e).__name__}: {str(e)[:300]}"); ok = False

    # 3. embedding
    t = time.time()
    vec = get_embeddings({"node": "smoke_embed"}).embed_query("fan-out dispersal of funds to many accounts")
    print(f"[3] embedding length: {len(vec)}  {time.time() - t:.1f}s")
    if len(vec) != s.embed_dimensions:
        print(f"    WARN: expected {s.embed_dimensions}"); ok = False

    led, eled = get_chat_ledger(), get_embed_ledger()
    print(f"chat ledger after: used in={led.used_input} out={led.used_output} calls={led.calls}  "
          f"remaining={led.remaining()}")
    print(f"embed ledger after: used={eled.used_input} (estimated) remaining={eled.remaining()['input']}")
    print("SMOKE OK" if ok else "SMOKE FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

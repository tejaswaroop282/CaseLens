"""Spend so far from the token ledger (Mongo llm_usage). Look up current prices yourself.

    python -m app.scripts.estimate_cost --price-in <USD per 1M input tokens> --price-out <USD per 1M output tokens>
                                       [--embed-price <USD per 1M embedding tokens>]
"""
from __future__ import annotations

import argparse
import sys


def spend(tokens_in: int, tokens_out: int, price_in: float, price_out: float) -> float:
    return tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--price-in", type=float, required=True)
    ap.add_argument("--price-out", type=float, required=True)
    ap.add_argument("--embed-price", type=float, default=0.0)
    a = ap.parse_args(argv)
    from app.config import get_settings
    from app.db import get_db
    s, db = get_settings(), get_db()
    rows = {r["_id"]: r for r in db.llm_usage.aggregate([
        {"$group": {"_id": {"$ifNull": ["$kind", "llm"]}, "i": {"$sum": "$input_tokens"},
                    "o": {"$sum": "$output_tokens"}, "n": {"$sum": 1}}}])}
    llm, emb = rows.get("llm", {"i": 0, "o": 0, "n": 0}), rows.get("embed", {"i": 0, "o": 0, "n": 0})
    by_node = list(db.llm_usage.aggregate([{"$match": {"kind": "llm"}},
                                           {"$group": {"_id": "$node", "i": {"$sum": "$input_tokens"},
                                                       "o": {"$sum": "$output_tokens"}, "n": {"$sum": 1}}},
                                           {"$sort": {"i": -1}}]))
    chat_usd = spend(llm["i"], llm["o"], a.price_in, a.price_out)
    emb_usd = emb["i"] / 1e6 * a.embed_price
    print(f"chat model {s.llm_model_id}: {llm['n']} calls, {llm['i']:,} in / {llm['o']:,} out tokens -> ${chat_usd:.4f}")
    for r in by_node:
        print(f"   {str(r['_id']):18} {r['n']:5} calls {r['i']:>10,} in {r['o']:>9,} out")
    print(f"embeddings {s.embed_model_id}: {emb['n']} calls, ~{emb['i']:,} tokens (estimated) -> ${emb_usd:.4f}")
    print(f"TOTAL ${chat_usd + emb_usd:.4f}  (budget limits: {s.llm_token_budget_input:,} in / "
          f"{s.llm_token_budget_output:,} out / {s.embed_token_budget:,} embed tokens)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

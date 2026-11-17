"""Investigate alerts from the command line (M4 acceptance: 5 alerts).

    python -m app.scripts.investigate --scenario-id <id> --n 5 --dry-run
    python -m app.scripts.investigate --scenario-id <id> --n 5 [--yes]
    python -m app.scripts.investigate --alert-id <id> [--alert-id <id> ...] [--yes]

Alerts are chosen by a seeded sample of alert ids (never by truth). Prints a token estimate first and
refuses to start if it exceeds the remaining budget."""
from __future__ import annotations

import argparse
import random
import sys

# Rough per-case estimates (docs/05; mine, not measured): ~7.5k in / 1.5k out, a retry adds ~4k / 0.8k.
EST_CASE_IN, EST_CASE_OUT, EST_RETRY_IN, EST_RETRY_OUT = 7500, 1500, 4000, 800


def estimate(n: int) -> dict:
    return {"input": n * (EST_CASE_IN + EST_RETRY_IN), "output": n * (EST_CASE_OUT + EST_RETRY_OUT)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--alert-id", action="append", default=[])
    ap.add_argument("--scenario-id")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)

    from app.config import get_settings
    from app.db import get_db
    from app.investigation.service import execute_investigation, start_investigation
    from app.llm import apply_langsmith_env, get_chat_ledger
    s = get_settings()
    db = get_db()
    ids = list(a.alert_id)
    if not ids:
        if not a.scenario_id:
            ap.error("give --alert-id or --scenario-id")
        pool = sorted(x["alert_id"] for x in db.alerts.find({"scenario_id": a.scenario_id, "status": "new"},
                                                            {"alert_id": 1}))
        ids = random.Random(s.random_seed).sample(pool, min(a.n, len(pool)))
    if not ids:
        print("no alerts to investigate"); return 1
    est, rem = estimate(len(ids)), get_chat_ledger().remaining()
    print(f"alerts={len(ids)} model={s.llm_model_id} prompt={s.prompt_version} "
          f"max_calls_per_case={s.max_llm_calls_per_case}")
    print(f"estimated tokens (worst case, one retry each): in={est['input']} out={est['output']} | "
          f"remaining: in={rem['input']} out={rem['output']}")
    if est["input"] > rem["input"] or est["output"] > rem["output"]:
        print("REFUSED: the estimate exceeds the remaining token budget"); return 2
    if a.dry_run:
        print("dry run: no AI calls made"); return 0
    if not a.yes and input("Run now? [y/N] ").strip().lower() != "y":
        print("cancelled"); return 1

    apply_langsmith_env()
    print(f"\n{'alert_id':17} {'status':20} {'verdict':18} {'checks':>6} {'calls':>5} {'tok_in':>7} {'tok_out':>7} {'sec':>6}")
    for aid in ids:
        case = execute_investigation(db, start_investigation(db, aid))
        cf, ck = case.get("case_file") or {}, case.get("checker") or {}
        print(f"{aid:17} {case['status']:20} {str(cf.get('verdict')):18} {str(ck.get('attempts', '-')):>6} "
              f"{case['llm_calls']:>5} {case['tokens']['input']:>7} {case['tokens']['output']:>7} "
              f"{case['timings'].get('total_seconds', 0):>6}")
        if case.get("error"):
            print(f"   error: {case['error']['code']}: {case['error']['message'][:160]}")
        for e in (ck.get("errors") or [])[:5]:
            print(f"   checker: {e[:160]}")
        if case["status"] == "failed" and case["error"]["code"] == "llm_budget_exhausted":
            print("STOPPED: token budget used up"); break
    led = get_chat_ledger()
    print(f"\nledger: used in={led.used_input} out={led.used_output} calls={led.calls} remaining={led.remaining()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

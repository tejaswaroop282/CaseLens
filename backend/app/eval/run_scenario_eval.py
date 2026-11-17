"""Eval set 1: scenario parsing on 20 worries (docs/05 section 3).

    python -m app.eval.run_scenario_eval --dry-run      # estimate tokens, no AI calls
    python -m app.eval.run_scenario_eval [--yes] [--limit N]

Uses LangSmith (dataset + experiment) when LANGSMITH_TRACING is on and a key is set; otherwise runs
locally. Either way the same metrics are printed and stored in Mongo `eval_reports`."""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

from app.budget import TokenBudgetExceeded
from app.config import get_settings
from app.eval.evaluators import EVALUATORS, load_jsonl, score_row, summarize

DATASET_FILE = "scenario_parse.jsonl"
DATASET_NAME = "caselens-scenario-parse"
EST_IN, EST_OUT, RETRY_ALLOWANCE = 600, 200, 1.3        # per worry (estimates, not measured)


def estimate(n: int) -> dict:
    return {"input": int(n * EST_IN * RETRY_ALLOWANCE), "output": int(n * EST_OUT * RETRY_ALLOWANCE)}


def make_target(formats: list[str], slice_hours: int, results: list):
    from app.llm import get_chat_ledger
    from app.scenario.parse import ScenarioParseError, parse_intent

    def target(inputs: dict) -> dict:
        led = get_chat_ledger()
        before = (led.used_input, led.used_output)
        t0 = time.time()
        out = {"spec": None, "error": None}
        try:
            out["spec"] = parse_intent(inputs["intent"], formats, slice_hours,
                                       metadata={"eval": DATASET_NAME, "row_id": inputs.get("id")}).model_dump()
        except ScenarioParseError as e:
            out["error"] = f"parse_failed: {e}"
        out["latency_s"] = round(time.time() - t0, 3)
        out["tokens"] = {"input": led.used_input - before[0], "output": led.used_output - before[1]}
        results.append({"id": inputs.get("id"), **out})
        return out
    return target


def run_langsmith(rows, target, s) -> None:
    from langsmith import Client
    client = Client()
    if not client.has_dataset(dataset_name=DATASET_NAME):
        ds = client.create_dataset(dataset_name=DATASET_NAME, description="CaseLens eval set 1: 20 worries")
        for r in rows:
            client.create_example(inputs={"id": r["id"], "intent": r["intent"]}, outputs={"expected": r["expected"]},
                                  dataset_id=ds.id)
    def adapt(ev):
        def evaluator(outputs: dict, reference_outputs: dict) -> dict:   # LangSmith maps args by these names
            return ev(outputs, reference_outputs["expected"])
        evaluator.__name__ = ev.__name__
        return evaluator
    wrapped = [adapt(ev) for ev in EVALUATORS]
    client.evaluate(target, data=DATASET_NAME, evaluators=wrapped, experiment_prefix=f"scenario-parse-{s.prompt_version}",
                    metadata={"model_id": s.llm_model_id, "prompt_version": s.prompt_version},
                    max_concurrency=1)          # sequential: keeps per-row token accounting exact


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args(argv)

    from app.db import get_db
    from app.llm import apply_langsmith_env, get_chat_ledger
    from app.scenario.service import data_context
    s = get_settings()
    db = get_db()
    rows = load_jsonl(DATASET_FILE)[: a.limit]
    slice_hours, formats = data_context(db)
    est, rem = estimate(len(rows)), get_chat_ledger().remaining()
    print(f"rows={len(rows)} model={s.llm_model_id} prompt={s.prompt_version} slice_hours={slice_hours}")
    print(f"estimated tokens: in={est['input']} out={est['output']} | remaining budget: in={rem['input']} "
          f"out={rem['output']}")
    if est["input"] > rem["input"] or est["output"] > rem["output"]:
        print("REFUSED: the estimate exceeds the remaining token budget"); return 2
    if a.dry_run:
        print("dry run: no AI calls made"); return 0
    if not a.yes and input("Run now? [y/N] ").strip().lower() != "y":
        print("cancelled"); return 1

    apply_langsmith_env()
    results: list = []
    target = make_target(formats, slice_hours, results)
    use_ls = s.langsmith_tracing and bool(s.langsmith_api_key)
    try:
        if use_ls:
            run_langsmith(rows, target, s)
        else:
            for r in rows:
                target({"id": r["id"], "intent": r["intent"]})
    except TokenBudgetExceeded as e:
        print(f"STOPPED: {e}")

    by_id = {r["id"]: r for r in rows}
    per_row = [{**res, "scores": score_row(res, by_id[res["id"]]["expected"])} for res in results]
    summary = summarize([p["scores"] for p in per_row])
    n = len(per_row) or 1
    summary["mean_latency_s"] = round(sum(p["latency_s"] for p in per_row) / n, 3)
    summary["total_tokens"] = {"input": sum(p["tokens"]["input"] for p in per_row),
                               "output": sum(p["tokens"]["output"] for p in per_row)}
    db.eval_reports.insert_one({"eval": DATASET_NAME, "ts": datetime.now(timezone.utc), "model_id": s.llm_model_id,
                                "prompt_version": s.prompt_version, "langsmith": use_ls, "n": len(per_row),
                                "summary": summary, "rows": per_row})
    print(f"\n{'id':5} {'dir':6} {'schema':>6} {'dir_ok':>6} {'params':>6} {'reject':>6}  error")
    for p in per_row:
        sc = p["scores"]; d = (p["spec"] or {}).get("direction")
        f = lambda v: "-" if v is None else str(v)                          # noqa: E731
        print(f"{p['id']:5} {str(d):6} {f(sc['schema_valid']):>6} {f(sc['direction_match']):>6} "
              f"{f(sc['params_in_expectation']):>6} {f(sc['correct_rejection']):>6}  {p['error'] or ''}")
    print("\nSUMMARY", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Eval set 2: case files on labeled alerts, three systems compared (docs/05 section 4).

    python -m app.eval.run_case_eval --split dev --tune --dry-run   # estimate only
    python -m app.eval.run_case_eval --split dev --tune [--reuse] [--yes]
    python -m app.eval.run_case_eval --split eval [--reuse] [--yes]  # final runs only

A = rule only (every alert to a human); B = code baseline (thresholds tuned on dev only);
C = CaseLens (full graph; needs_human_rewrite / failed count as needs_review).
Writes the results table to docs/results/ and Mongo eval_reports."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone

from app.config import REPO_ROOT, get_settings
from app.eval.case_metrics import system_metrics, tune_baseline, verdict_from_case
from app.eval.evaluators import DATA_DIR, load_jsonl
from app.scripts.investigate import estimate

BASELINE_FILE = DATA_DIR / "baseline_params.json"
FINISHED = ("checked", "needs_human_rewrite", "failed", "decided")


def check_budget(n_new: int, remaining: dict) -> tuple[bool, dict]:
    est = estimate(n_new)
    return est["input"] <= remaining["input"] and est["output"] <= remaining["output"], est


def reusable_case(db, alert_id: str, s) -> dict | None:
    return db.cases.find_one({"alert_id": alert_id, "status": {"$in": list(FINISHED)},
                              "prompt_version": s.prompt_version, "model_ids.llm": s.llm_model_id},
                             {"_id": 0}, sort=[("created_at", -1)])


def fmt(x, pct=True):
    if x is None:
        return "—"
    return f"{x * 100:.1f}%" if pct else str(x)


def results_markdown(split: str, meta: dict, base: dict, res: dict, s, failures: list[str]) -> str:
    a, b, c = res["A"], res["B"], res.get("C")
    lines = [f"# Case-file evaluation — {split} split", "",
             f"Run {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · model `{s.llm_model_id}` · prompt `{s.prompt_version}` · "
             f"TYPOLOGY_TOP_K {s.typology_top_k} · seed {s.random_seed}",
             f"Scenario `{meta.get('scenario_id')}`: {json.dumps((meta.get('spec') or {}).get('params'))} · "
             f"n = {a['n']} ({a['n_suspicious']} suspicious / {a['n_not_suspicious']} not)", "",
             "| System | n | False-clear | Auto-clear | Review load | Checker after-retry | Avg latency | Avg tokens (in/out) |",
             "|---|---|---|---|---|---|---|---|",
             f"| A. Rule only | {a['n']} | {fmt(a['false_clear_rate'])} | {fmt(a['auto_clear_rate'])} | {fmt(a['review_load'])} | — | — | — |",
             f"| B. Code baseline (CV_MAX={base['cv_max']}, REPEAT_MIN={base['repeat_min']}) | {b['n']} | "
             f"{fmt(b['false_clear_rate'])} | {fmt(b['auto_clear_rate'])} | {fmt(b['review_load'])} | — | — | — |"]
    if c:
        lines.append(f"| C. CaseLens ({s.llm_model_id}, prompt {s.prompt_version}) | {c['n']} | {fmt(c['false_clear_rate'])} | "
                     f"{fmt(c['auto_clear_rate'])} | {fmt(c['review_load'])} | {fmt(c.get('checker_after_retry_rate'))} | "
                     f"{c.get('avg_latency_s', '—')} s | {c['avg_tokens']['input']}/{c['avg_tokens']['output']} |")
        lines += ["", f"CaseLens detail: checker first-pass {fmt(c.get('checker_first_pass_rate'))}, "
                      f"citation validity {fmt(c.get('citation_validity'))}, needs-rewrite {fmt(c.get('needs_rewrite_rate'))}, "
                      f"failed {fmt(c.get('failed_rate'))}, total tokens {c['total_tokens']['input']} in / "
                      f"{c['total_tokens']['output']} out."]
    if meta.get("notes"):
        lines += ["", "Split notes: " + "; ".join(meta["notes"])]
    lines += ["", "## Cases to look at (fill in the explanation by hand)", ""] + (failures or ["- none"])
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", choices=["dev", "eval"], default="dev")
    ap.add_argument("--tune", action="store_true", help="tune the code baseline (dev split only)")
    ap.add_argument("--reuse", action="store_true", help="reuse finished cases with the same model and prompt version")
    ap.add_argument("--skip-c", action="store_true", help="only systems A and B (no AI calls)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    if a.tune and a.split != "dev":
        ap.error("--tune is allowed on the dev split only")

    from app.db import get_db
    from app.investigation.facts import build_fact_sheet
    from app.investigation.service import execute_investigation, start_investigation
    from app.investigation.triage_baseline import CV_MAX, REPEAT_MIN, triage
    from app.llm import apply_langsmith_env, get_chat_ledger
    s, db = get_settings(), get_db()
    path = DATA_DIR / f"case_{a.split}.jsonl"
    if not path.exists():
        print("no split files yet: run python -m app.scripts.make_dev_split --scenario-id <id>"); return 2
    rows = load_jsonl(path.name)
    meta = json.loads((DATA_DIR / "case_split_meta.json").read_text(encoding="utf-8"))

    # ---- C: plan AI work before spending anything
    cases: dict[str, dict] = {}
    todo = []
    if not a.skip_c:
        for r in rows:
            c = reusable_case(db, r["alert_id"], s) if a.reuse else None
            if c:
                cases[r["alert_id"]] = c
            else:
                todo.append(r["alert_id"])
        ok, est = check_budget(len(todo), get_chat_ledger().remaining())
        print(f"split={a.split} alerts={len(rows)} new investigations={len(todo)} reused={len(cases)}")
        print(f"estimated tokens (worst case): in={est['input']} out={est['output']} | remaining={get_chat_ledger().remaining()}")
        if not ok:
            print("REFUSED: the estimate exceeds the remaining token budget"); return 2
        if a.dry_run:
            print("dry run: no AI calls made"); return 0
        if todo and not a.yes and input("Run now? [y/N] ").strip().lower() != "y":
            print("cancelled"); return 1
        apply_langsmith_env()
        for i, aid in enumerate(todo, 1):
            t = time.time()
            if db.cases.find_one({"alert_id": aid, "status": {"$in": ["queued", "running"]}}):
                db.cases.update_many({"alert_id": aid, "status": {"$in": ["queued", "running"]}},
                                     {"$set": {"status": "failed", "error": {"code": "interrupted", "message": "stale"}}})
            cases[aid] = execute_investigation(db, start_investigation(db, aid))
            print(f"  [{i}/{len(todo)}] {aid} -> {cases[aid]['status']} ({time.time() - t:.1f}s)")
            if (cases[aid].get("error") or {}).get("code") == "llm_budget_exhausted":
                print("STOPPED: token budget used up"); return 3

    # ---- B: facts by code, thresholds tuned on dev only
    facts = {r["alert_id"]: {f.id: f for f in build_fact_sheet(db, r["alert_id"])[0]} for r in rows}
    if a.tune:
        base = tune_baseline(rows, facts)
        BASELINE_FILE.write_text(json.dumps(base, indent=2), encoding="utf-8")
        print("tuned baseline on dev:", base)
    elif BASELINE_FILE.exists():
        base = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    else:
        base = {"cv_max": CV_MAX, "repeat_min": REPEAT_MIN, "note": "defaults (not tuned)"}

    res = {"A": system_metrics([{**r, "verdict": "needs_review"} for r in rows]),
           "B": system_metrics([{**r, "verdict": triage(facts[r["alert_id"]], base["cv_max"], base["repeat_min"])}
                                for r in rows])}
    failures = []
    if not a.skip_c:
        c_rows = [{**r, "verdict": verdict_from_case(cases.get(r["alert_id"])), "case": cases.get(r["alert_id"])}
                  for r in rows]
        res["C"] = system_metrics(c_rows)
        for r in c_rows:
            c = r["case"] or {}
            if r["is_suspicious"] and r["verdict"] == "likely_legitimate":
                failures.append(f"- FALSE CLEAR `{r['alert_id']}` (case `{c.get('case_id')}`): AI said likely_legitimate; truth: suspicious.")
            elif c.get("status") in ("needs_human_rewrite", "failed"):
                why = (c.get("error") or {}).get("code") or "; ".join((c.get("checker") or {}).get("errors", [])[:2])
                failures.append(f"- {c.get('status')} `{r['alert_id']}` (case `{c.get('case_id')}`): {why}")

    md = results_markdown(a.split, meta, base, res, s, failures)
    out_dir = REPO_ROOT / "docs" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"case_eval_{a.split}_{datetime.now(timezone.utc):%Y%m%d_%H%M}.md"
    out.write_text(md, encoding="utf-8")
    db.eval_reports.insert_one({"eval": f"case_{a.split}", "ts": datetime.now(timezone.utc), "model_id": s.llm_model_id,
                                "prompt_version": s.prompt_version, "baseline": base, "results": res,
                                "case_ids": {k: v.get("case_id") for k, v in cases.items()}})
    print("\n" + md + f"\nwritten to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

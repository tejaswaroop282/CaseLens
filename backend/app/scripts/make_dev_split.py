"""Build eval set 2 (docs/05 section 4.1): 10 dev + 30 eval alerts, disjoint, balanced when possible.

    python -m app.scripts.make_dev_split --scenario-id <id>

The scenario must be approved, completed and direction 'out'. Writes app/eval/data/case_dev.jsonl and
case_eval.jsonl ({alert_id, is_suspicious}) plus case_split_meta.json. Only evaluation code reads them."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from app.eval.case_metrics import make_splits
from app.eval.evaluators import DATA_DIR


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenario-id", required=True)
    ap.add_argument("--force", action="store_true", help="overwrite existing split files")
    a = ap.parse_args(argv)
    from app.config import get_settings
    from app.db import get_db
    db, s = get_db(), get_settings()
    sc = db.scenarios.find_one({"scenario_id": a.scenario_id})
    if not sc or sc["status"] != "completed" or sc["spec"]["direction"] != "out":
        print("the scenario must exist, be completed, and have direction 'out'"); return 2
    if (DATA_DIR / "case_eval.jsonl").exists() and not a.force:
        print("split files exist; the same alerts must be used every run. Use --force only to start over."); return 2
    truth = list(db.alert_truth.find({"scenario_id": a.scenario_id}, {"_id": 0, "alert_id": 1, "is_suspicious": 1}))
    sp = make_splits(truth, s.random_seed)
    for name in ("dev", "eval"):
        with open(DATA_DIR / f"case_{name}.jsonl", "w", encoding="utf-8") as f:
            for r in sp[name]:
                f.write(json.dumps(r) + "\n")
    meta = {"scenario_id": a.scenario_id, "spec": sc["spec"], "seed": s.random_seed, "notes": sp["notes"],
            "alerts_in_scenario": len(truth), "suspicious_in_scenario": sum(t["is_suspicious"] for t in truth),
            "created_at": datetime.now(timezone.utc).isoformat()}
    (DATA_DIR / "case_split_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    for name in ("dev", "eval"):
        n_s = sum(r["is_suspicious"] for r in sp[name])
        print(f"{name}: {len(sp[name])} alerts ({n_s} suspicious, {len(sp[name]) - n_s} not)")
    for n in sp["notes"]:
        print("NOTE:", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())

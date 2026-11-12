"""Pipeline entry point.

    python -m pipeline.run --step raw|staging|labels|docs|dq|all [--force]

Order for `all`: raw -> staging -> labels -> docs -> dq. Each step is skipped when its config_hash is
unchanged unless --force. `docs` is skipped (with a message) while docs/SOURCES.yaml does not exist."""
from __future__ import annotations

import argparse
import sys

from app.db import get_db, ping
from pipeline.common import sources_yaml

STEPS = ("raw", "staging", "labels", "docs", "dq")


def run_step(db, step: str, force: bool) -> bool:
    if step == "raw":
        from pipeline.load_raw import run_raw; print("raw:", run_raw(db, force) or "skipped (unchanged)")
    elif step == "staging":
        from pipeline.stage import run_staging; print("staging:", run_staging(db, force) or "skipped (unchanged)")
    elif step == "labels":
        from pipeline.labels import run_labels; print("labels:", run_labels(db, force) or "skipped (unchanged)")
    elif step == "docs":
        if not sources_yaml().exists():
            print("docs: skipped, docs/SOURCES.yaml does not exist yet (PDFs not approved)")
            return True
        from pipeline.ingest_docs import run_docs; print("docs:", run_docs(db, force) or "skipped (unchanged)")
    elif step == "dq":
        from pipeline.dq import run_dq
        ok, _ = run_dq(db)
        return ok
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--step", required=True, choices=[*STEPS, "all"])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if not ping():
        print("MongoDB is not reachable. Start it: docker compose up -d mongo"); return 2
    db = get_db()
    for step in (STEPS if a.step == "all" else (a.step,)):
        if not run_step(db, step, a.force):
            print(f"{step}: FAILED"); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

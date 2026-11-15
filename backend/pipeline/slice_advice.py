"""Recommend the smallest SLICE_HOURS with enough complete fan blocks. Reads only the patterns file.

    python -m pipeline.slice_advice [--path data/ibm/HI-Small_Patterns.txt]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from pipeline.common import PATTERNS_FILE, ibm_dir
from pipeline.patterns import FAN_TYPES, PatternBlock, parse_file

HOURS = (24, 48, 72, 96, 120, 144, 168, 216, 264, 312, 432)   # IBM fan blocks span up to 96 h
MIN_BLOCKS = 10


def midnight(ts: datetime) -> datetime:
    return ts.replace(hour=0, minute=0, second=0, microsecond=0)


def advise(blocks: list[PatternBlock], hours=HOURS, min_blocks: int = MIN_BLOCKS) -> dict:
    fan = [b for b in blocks if b.pattern_type in FAN_TYPES and b.first_ts]
    all_ts = [b.first_ts for b in blocks if b.first_ts]
    if not all_ts:
        raise ValueError("no timestamps found in the patterns file")
    origin = midnight(min(all_ts))
    table = []
    for h in hours:
        end = origin + timedelta(hours=h)
        counts = {t: sum(1 for b in fan if b.pattern_type == t and b.last_ts < end) for t in FAN_TYPES}
        table.append({"hours": h, **counts})
    ok = [r for r in table if all(r[t] >= min_blocks for t in FAN_TYPES)]
    rec = ok[0]["hours"] if ok else hours[-1]
    return {"origin": origin, "table": table, "recommended": rec, "sufficient": bool(ok),
            "fan_totals": {t: sum(1 for b in fan if b.pattern_type == t) for t in FAN_TYPES},
            "types": sorted({b.pattern_type for b in blocks})}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", type=Path, default=ibm_dir() / PATTERNS_FILE)
    a = ap.parse_args(argv)
    if not a.path.exists():
        print(f"not found: {a.path} (download it first, or run the raw step to fetch it from S3)")
        return 1
    blocks = parse_file(a.path)
    r = advise(blocks)
    print(f"blocks: {len(blocks)}  types: {', '.join(r['types'])}")
    print(f"fan blocks in whole file: {r['fan_totals']}")
    print(f"approximate origin (midnight of earliest pattern timestamp): {r['origin']:%Y-%m-%d %H:%M} UTC")
    print(f"{'hours':>6} {'fan_out':>8} {'fan_in':>7}   (blocks fully inside the first H hours)")
    for row in r["table"]:
        print(f"{row['hours']:>6} {row['fan_out']:>8} {row['fan_in']:>7}")
    if r["sufficient"]:
        print(f"RECOMMENDED SLICE_HOURS={r['recommended']} (smallest with >= {MIN_BLOCKS} blocks of each type)")
    else:
        print(f"No H has >= {MIN_BLOCKS} blocks of each type. Largest checked: SLICE_HOURS={r['recommended']}. "
              "Pattern recall and evaluation sets will be small; say so in the README.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

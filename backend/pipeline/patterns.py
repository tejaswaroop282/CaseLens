"""Parser for HI-Small_Patterns.txt.

Expected shape (verify on the real file; findings go to docs/DATA_NOTES.md):
    BEGIN LAUNDERING ATTEMPT - FAN-OUT
    <csv transaction line, same 11 columns as Trans.csv>
    END LAUNDERING ATTEMPT - FAN-OUT
Some headers carry a suffix, e.g. "CYCLE:  Max 10 hops"; the type is the text before ':'.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

from pipeline.common import KEY_COLS, TS_FORMAT, row_key

BEGIN_RE = re.compile(r"^\s*BEGIN LAUNDERING ATTEMPT\s*-\s*(.+?)\s*$")
END_RE = re.compile(r"^\s*END LAUNDERING ATTEMPT")
FAN_TYPES = ("fan_out", "fan_in")


def normalize_type(raw: str) -> str:
    """'FAN-OUT' -> 'fan_out'; 'CYCLE:  Max 10 hops' -> 'cycle'."""
    base = raw.split(":", 1)[0].strip().lower()
    return re.sub(r"[\s\-]+", "_", base)


@dataclass
class PatternLine:
    fields: list[str]
    ts: Optional[datetime]
    key: str


@dataclass
class PatternBlock:
    pattern_id: str
    pattern_type: str
    raw_type: str
    lines: list[PatternLine] = field(default_factory=list)

    @property
    def first_ts(self) -> Optional[datetime]:
        ts = [ln.ts for ln in self.lines if ln.ts]
        return min(ts) if ts else None

    @property
    def last_ts(self) -> Optional[datetime]:
        ts = [ln.ts for ln in self.lines if ln.ts]
        return max(ts) if ts else None


def parse_ts(raw: str) -> Optional[datetime]:
    try:
        return datetime.strptime(raw.strip(), TS_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_lines(lines: Iterable[str], dataset: str = "HI-Small") -> Iterator[PatternBlock]:
    """Yield blocks in file order with pattern_id = f"{dataset}-P{n:05d}". Lines outside a block are ignored."""
    cur: Optional[PatternBlock] = None
    n = 0
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        if m := BEGIN_RE.match(line):
            n += 1
            cur = PatternBlock(f"{dataset}-P{n:05d}", normalize_type(m.group(1)), m.group(1).strip())
            continue
        if END_RE.match(line):
            if cur is not None:
                yield cur
            cur = None
            continue
        if cur is None:
            continue
        fields = [f.strip() for f in next(csv.reader([line]))]
        if len(fields) < len(KEY_COLS):
            continue
        cur.lines.append(PatternLine(fields, parse_ts(fields[0]), row_key(fields[:len(KEY_COLS)])))
    if cur is not None:          # file ended inside a block
        yield cur


def parse_file(path: Path) -> list[PatternBlock]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(parse_lines(f))

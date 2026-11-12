from __future__ import annotations
import math, re
from dataclasses import dataclass, field
from typing import Any, Iterable
from models import CaseFile, Fact, Claim

NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(\s?%)?")
ID_RE = re.compile(r"\b[0-9A-F]{8,12}\b")     # account-id shape; make configurable per dataset

@dataclass
class CheckResult:
    passed: bool
    errors: list[str] = field(default_factory=list)

def _flatten_numbers(v: Any) -> Iterable[float]:
    if isinstance(v, bool): return
    if isinstance(v, (int, float)): yield float(v)
    elif isinstance(v, dict):
        for x in v.values(): yield from _flatten_numbers(x)
    elif isinstance(v, (list, tuple)):
        for x in v: yield from _flatten_numbers(x)
    elif isinstance(v, str):
        for m in NUM_RE.finditer(v):
            yield float((m.group(1) + (m.group(2) or "")).replace(",", ""))

def _flatten_strings(v: Any) -> Iterable[str]:
    if isinstance(v, str): yield v
    elif isinstance(v, dict):
        for k, x in v.items(): yield str(k); yield from _flatten_strings(x)
    elif isinstance(v, (list, tuple)):
        for x in v: yield from _flatten_strings(x)

def _matches(x: float, decimals: int, is_pct: bool, refs: list[float]) -> bool:
    cands = [x / 100.0, x] if is_pct else [x]
    for c in cands:
        for y in refs:
            if math.isclose(c, y, rel_tol=0, abs_tol=1e-9): return True
            if round(y, decimals) == round(c, decimals): return True
            if is_pct and round(y * 100, decimals) == round(x, decimals): return True
    return False

def check_claim(c: Claim, facts: dict[str, Fact], chunk_ids: set[str], where: str) -> list[str]:
    errs: list[str] = []
    if not c.fact_ids and not c.chunk_ids:
        return [f"{where}: claim has no fact_ids or chunk_ids"]
    for fid in c.fact_ids:
        if fid not in facts: errs.append(f"{where}: unknown fact id {fid}")
    for cid in c.chunk_ids:
        if cid not in chunk_ids: errs.append(f"{where}: unknown chunk id {cid}")
    refs = [n for fid in c.fact_ids if fid in facts for n in _flatten_numbers(facts[fid].value)]
    ref_text = " ".join(s for fid in c.fact_ids if fid in facts for s in _flatten_strings(facts[fid].value))
    if c.fact_ids:                                   # numbers are only checked against facts
        for m in NUM_RE.finditer(c.text):
            raw = (m.group(1) + (m.group(2) or "")).replace(",", "")
            dec = len(m.group(2)) - 1 if m.group(2) else 0
            if not _matches(float(raw), dec, bool(m.group(3)), refs):
                errs.append(f"{where}: number '{m.group(0).strip()}' not found in referenced facts {c.fact_ids}")
    for tok in ID_RE.findall(c.text):
        if tok not in ref_text:
            errs.append(f"{where}: id '{tok}' not found in referenced facts")
    return errs

def check_case_file(cf: CaseFile, facts_list: list[Fact], chunk_ids: set[str],
                    hard_red_flag: bool = False) -> CheckResult:
    facts = {f.id: f for f in facts_list}
    errs: list[str] = []
    if not cf.claims: errs.append("claims: at least one claim is required")
    for i, c in enumerate(cf.claims): errs += check_claim(c, facts, chunk_ids, f"claims[{i}]")
    for i, c in enumerate(cf.benign_explanations): errs += check_claim(c, facts, chunk_ids, f"benign[{i}]")
    for i, c in enumerate(cf.typology_context):
        if not c.chunk_ids: errs.append(f"typology[{i}]: needs chunk_ids")
        else: errs += check_claim(c, facts, chunk_ids, f"typology[{i}]")
        if not c.fact_ids and NUM_RE.search(c.text):
            errs.append(f"typology[{i}]: statements that cite only documents must not contain numbers")
    if cf.verdict == "likely_legitimate":
        if not cf.benign_explanations: errs.append("verdict: likely_legitimate needs at least one benign explanation")
        if hard_red_flag: errs.append("verdict: likely_legitimate not allowed when a hard red flag exists")
    return CheckResult(passed=not errs, errors=errs)

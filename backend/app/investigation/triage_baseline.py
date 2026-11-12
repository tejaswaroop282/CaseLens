"""Code-only baseline (docs/03 section 9): same facts, no LLM. Tune on the dev split only."""
from __future__ import annotations

from app.models import Fact

CV_MAX = 0.05        # amounts almost identical
REPEAT_MIN = 0.5     # at least half of counterparties seen before


def triage(facts: dict[str, Fact], cv_max: float = CV_MAX, repeat_min: float = REPEAT_MIN) -> str:
    f7 = facts["F7"].value
    f9 = facts["F9"].value
    if f9 and f9.get("cv") is not None and f9["cv"] <= cv_max and f7 is not None and f7 >= repeat_min:
        return "likely_legitimate"
    return "needs_review"

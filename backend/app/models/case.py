"""Case models (from reference/models.py)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Verdict = Literal["likely_legitimate", "needs_review", "likely_suspicious"]


class Fact(BaseModel):
    id: str                      # "F0".."F10"
    label: str
    value: Any                   # number, string, list or dict of numbers/strings
    unit: Optional[str] = None
    source: str                  # name of the function/query that produced it


class Claim(BaseModel):
    text: str = Field(max_length=400)
    fact_ids: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)


class TypologyNotes(BaseModel):
    items: list[Claim] = Field(default_factory=list, max_length=3)          # each must have chunk_ids


class BenignNotes(BaseModel):
    explanations: list[Claim] = Field(default_factory=list, max_length=4)   # each must have fact_ids
    missing_evidence: list[str] = Field(default_factory=list, max_length=6)


class CaseFile(BaseModel):
    verdict: Verdict
    summary: str = Field(max_length=800)
    claims: list[Claim] = Field(max_length=12)
    benign_explanations: list[Claim] = Field(default_factory=list, max_length=6)
    typology_context: list[Claim] = Field(default_factory=list, max_length=6)
    missing_evidence: list[str] = Field(default_factory=list, max_length=8)
    limitations: str = Field(default="", max_length=500)

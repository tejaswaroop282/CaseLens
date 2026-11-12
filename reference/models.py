from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, model_validator

Direction = Literal["out", "in"]     # "out" = one sender, many receivers; "in" = many senders, one receiver

class ScenarioParams(BaseModel):
    min_counterparties: int = Field(ge=3, le=200)
    window_hours: int = Field(ge=1, le=240)       # the service also checks window_hours <= slice length
    payment_formats: Optional[list[str]] = None    # must be values that exist in the data (checked by the service)

class ScenarioSpec(BaseModel):
    direction: Optional[Direction] = None      # null means: this worry is not the supported pattern
    params: Optional[ScenarioParams] = None
    legitimate_lookalikes: list[str] = Field(default_factory=list, max_length=8)
    rationale: str = Field(default="", max_length=600)
    unsupported_reason: Optional[str] = None

    @model_validator(mode="after")
    def _consistent(self):
        if self.direction is None:
            if not self.unsupported_reason:
                raise ValueError("unsupported_reason is required when direction is null")
            if self.params is not None:
                raise ValueError("params must be null when direction is null")
        else:
            if self.params is None:
                raise ValueError("params are required when direction is set")
            if self.unsupported_reason:
                raise ValueError("unsupported_reason must be null when direction is set")
        return self

Verdict = Literal["likely_legitimate", "needs_review", "likely_suspicious"]

class Fact(BaseModel):
    id: str                      # "F1".."F10"
    label: str
    value: Any                   # number, string, list or dict of numbers/strings
    unit: Optional[str] = None
    source: str                  # name of the function/query that produced it

class Claim(BaseModel):
    text: str = Field(max_length=400)
    fact_ids: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)

class CaseFile(BaseModel):
    verdict: Verdict
    summary: str = Field(max_length=800)
    claims: list[Claim] = Field(max_length=12)
    benign_explanations: list[Claim] = Field(default_factory=list, max_length=6)
    typology_context: list[Claim] = Field(default_factory=list, max_length=6)
    missing_evidence: list[str] = Field(default_factory=list, max_length=8)
    limitations: str = Field(default="", max_length=500)

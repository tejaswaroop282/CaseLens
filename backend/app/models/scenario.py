"""Scenario models (from reference/models.py). One pattern: fan, direction out or in."""
from __future__ import annotations

from typing import Literal, Optional

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

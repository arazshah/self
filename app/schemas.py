from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "task",
    "reminder",
    "follow_up",
    "finance",
    "appointment",
    "project",
    "idea",
    "errand",
    "decision",
    "reflection",
]


class ExtractedItem(BaseModel):
    category: Category
    title: str = Field(min_length=1, max_length=500)
    body: str | None = None
    evidence: str | None = None
    due_raw: str | None = None
    due_at: datetime | None = None
    solar_date: str | None = None
    confidence: float = Field(ge=0, le=1)
    needs_confirmation: bool = True


class ExtractionResult(BaseModel):
    items: list[ExtractedItem] = Field(default_factory=list)
    clarification: str | None = None
    reflection_summary: str | None = None
    suggestion: str | None = None


class ResolvedDate(BaseModel):
    raw: str
    value: datetime | None = None
    solar_date: str | None = None
    needs_confirmation: bool = False
    clarification: str | None = None

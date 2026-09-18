"""API-only models (docs/api_contract.md, Models). Shared shapes come from
app/rulesets/schema.py; these are what the routes send and receive."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.rulesets.schema import DataClass

JobState = Literal["queued", "running", "paused", "done", "failed", "dead"]


class Job(BaseModel):
    job_id: str
    kind: str
    project: str
    tenderer: str | None = None
    state: JobState
    step: str | None = None
    progress: dict = Field(default_factory=dict)
    attempt: int = 1
    error: str | None = None
    ruleset_version: int | None = None
    created_at: float
    updated_at: float


class CheckRequest(BaseModel):
    tenderers: list[str] | None = Field(default=None, description="default: every tenderer with an uploaded offer")


class CheckResponse(BaseModel):
    job_ids: dict[str, str]


class PageCitation(BaseModel):
    """Where a value was read: the page, and a signed URL to its image. When the value is
    found on the page's text layer, `quote` is that text as the page has it, `box` its
    place and `image_url` renders it highlighted; on a scanned page all three stay plain
    (quote and box null). Verified quotes on scanned pages arrive with V4 (S4)."""

    doc_id: str
    file: str
    page: int
    image_url: str = Field(description="signed, short-lived; carries a signed `highlight` when `quote` is set. "
                                       "Use it as given: do not add or change query parameters")
    quote: str | None = Field(default=None, description="the text the value was read from, as on the page's text layer")
    box: list[float] | None = Field(default=None, min_length=4, max_length=4,
                                    description="[x0, y0, x1, y1] around `quote`, PDF points, origin top-left, y down")
    page_size: list[float] | None = Field(default=None, min_length=2, max_length=2,
                                          description="[width, height] of the page in PDF points, set with `box`")


class Correction(BaseModel):
    value: Any = None
    by: str
    reason: str
    model_value: Any = None


class FieldValue(BaseModel):
    value: Any = None
    redacted: bool = False
    confidence: float | None = None
    page: PageCitation | None = None
    correction: Correction | None = None
    model_value: Any = None


class CheckedField(BaseModel):
    field_id: str
    status: Literal["pass", "needs_review", "disqualified", "dormant"]
    note: str | None = None
    redacted: bool = False
    stage: str = "I"
    follow_up: dict | None = None


class Verdict(BaseModel):
    outcome: Literal["pass", "needs_review", "disqualified", "dormant"]
    worst: Literal["pass", "needs_review", "disqualified", "dormant"]
    part: str
    rule_ids: list[str]
    reason: str
    checks: list[CheckedField]
    evidence: list[PageCitation]


class StageSummary(BaseModel):
    outcome: Literal["pass", "needs_review", "disqualified", "dormant"]
    items: dict[str, str]


class BidResult(BaseModel):
    tenderer: str
    run_id: str
    ruleset_version: int
    fields: dict[str, dict[str, FieldValue]]      # letter -> field name -> value
    verdicts: dict[str, Verdict]                  # letter -> verdict
    stage1: StageSummary
    stage2: StageSummary | None = None
    trace: dict | None = None
    cost: dict = Field(default_factory=dict)
    review_confirmed_by: str | None = None


class Document(BaseModel):
    doc_id: str
    file: str
    path: str = Field(description="relative to the project, as a rule-set Citation.file names it, "
                                  "e.g. 'tender/09 Schedules.pdf' or 'bids/Tenderer_A/offer.pdf'")
    kind: Literal["tender", "bid"]
    tenderer: str | None = None
    pages: int
    data_class: DataClass


class Page(BaseModel):
    page: int
    has_text: bool
    label: str | None = None
    title: str | None = None
    summary: str | None = None
    signed: bool | None = None
    has_table: bool | None = None
    image_url: str


class RuleSetVersion(BaseModel):
    version: int
    status: Literal["draft", "confirmed"]
    parent_version: int | None = None
    created_by: str | None = None
    created_at: float | None = None
    confirmed_by: str | None = None
    confirmed_at: float | None = None


class Event(BaseModel):
    id: int
    kind: str
    project: str
    subject: str | None = None
    before: Any = None
    after: Any = None
    user: str
    reason: str | None = None
    at: float


class EventPage(BaseModel):
    items: list[Event]
    next_cursor: str | None = None


class JobPage(BaseModel):
    items: list[Job]
    next_cursor: str | None = None

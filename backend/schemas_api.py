"""API-only models (docs/api_contract.md, Models). Shared shapes come from
app/rulesets/schema.py; these are what the routes send and receive."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.rulesets.schema import Citation, DataClass, Edit, ItemNote, Part, TemplateRule

JobState = Literal["queued", "running", "paused", "done", "failed", "dead"]


class Progress(BaseModel):
    """How far a job's current step has got: `done` of `total` `unit`s (pages, calls, ...)."""

    done: int = 0
    total: int | None = None
    unit: str | None = None


class Job(BaseModel):
    job_id: str
    kind: str
    project: str
    tenderer: str | None = None
    state: JobState
    step: str | None = None
    progress: Progress = Field(default_factory=Progress)
    attempt: int = 1
    error: str | None = None
    ruleset_version: int | None = None
    created_at: datetime
    updated_at: datetime


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


class Verification(BaseModel):
    """V4's check of a value (S4). On a page with a text layer the value was looked for
    verbatim: found, `verified` with the quote on the citation and confidence 1. On a scanned
    page a second, independent read was compared with the first: agreement verifies,
    disagreement leaves the value unverified with `second_value` kept for the reviewer.
    `verified` is null when nothing could be checked (redacted, blank on a text page, a
    signature on a text layer, no page). An unverified value is `needs_review`."""

    verified: bool | None = None
    method: Literal["text_layer", "second_read"] | None = None
    second_value: Any = None
    note: str | None = None


class FieldValue(BaseModel):
    value: Any = None
    redacted: bool = False
    confidence: float | None = Field(default=None, description="per field after V4: 1 for a value found on the "
                                     "text layer, the fraction of its words found otherwise; on a scan the mean "
                                     "of the two reads when they agree, half the lower when they differ")
    page: PageCitation | None = None
    correction: Correction | None = None
    model_value: Any = None
    verification: Verification | None = None


class CheckedField(BaseModel):
    field_id: str
    field: str | None = Field(default=None, description="the field's key inside BidResult.fields[letter]")
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
    created_at: datetime | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    updated_by: str | None = Field(default=None, description="who last saved the draft; confirm refuses that person")


class Event(BaseModel):
    id: int
    kind: str
    project: str
    subject: str | None = None
    before: Any = None
    after: Any = None
    user: str
    reason: str | None = None
    at: datetime


class EventPage(BaseModel):
    items: list[Event]
    next_cursor: str | None = None


class JobPage(BaseModel):
    items: list[Job]
    next_cursor: str | None = None


class ProjectStatus(BaseModel):
    """The legacy pipeline's state file: idle, running, waiting, done or error, with a detail line."""

    state: Literal["idle", "running", "waiting", "done", "error"] = "idle"
    detail: str | None = None
    updated: datetime | None = None


class Project(BaseModel):
    """A project as `GET /projects` lists it and `GET /projects/{pid}` describes it (the
    detail fields are null in the list)."""

    id: str
    name: str
    synthetic: bool = False
    data_class: DataClass = DataClass.CONFIDENTIAL
    created: datetime | None = None
    status: ProjectStatus = Field(default_factory=ProjectStatus, description="an object, not a string: read status.state")
    tender_files: list[str] | None = None
    bidders: list[str] | None = None
    extracted: list[str] | None = None
    has_rubric: bool | None = None
    has_evaluation: bool | None = None
    reports: list[str] | None = None


class CorrectionRequest(BaseModel):
    """The body of `PATCH /bids/{t}/fields/{letter}/{field}` (S4): correct a value, mark a
    document present or absent, or point at another page. `Correction` is the stored record."""

    value: Any = None
    present: bool | None = None
    page: int | None = None
    reason: str = Field(min_length=1)


class SlotPatch(BaseModel):
    name: str
    value: Any = None


class ItemPatch(BaseModel):
    """`PATCH /ruleset/items/{letter}` (S3): one of slot, rule, template or note, with a reason.
    A corrected slot keeps the model's value in `model_value`; the item becomes `edited`."""

    slot: SlotPatch | None = None
    rule: TemplateRule | None = None
    template: str | None = None
    note: ItemNote | None = None
    reason: str = Field(min_length=1)


class NewItem(BaseModel):
    """`POST /ruleset/items` (S3): an item a person adds from a clause; lettered x1, x2, ...
    and `edited` with the person's edit record."""

    title: str = Field(min_length=1)
    part: Part
    citation: Citation
    rules: list[TemplateRule] = Field(default_factory=list)
    reason: str = Field(min_length=1)


class DiffChange(BaseModel):
    letter: str
    fields: list[str]
    edit: Edit | None = Field(default=None, description="null when the rule builder, not a person, made the change")


class Diff(BaseModel):
    """`GET /ruleset/diff?from=&to=` (S3)."""

    model_config = ConfigDict(populate_by_name=True)

    from_version: int = Field(alias="from")
    to: int
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    changed: list[DiffChange] = Field(default_factory=list)


class ErrorDetail(BaseModel):
    code: str = Field(description="snake_case, e.g. validation_failed")
    message: str
    details: dict = Field(default_factory=dict)


class ErrorBody(BaseModel):
    """Every error response, 422 included (docs/api_contract.md, Conventions)."""

    error: ErrorDetail
    detail: str = Field(description="the message again, for the Streamlit UI until S5")


class BuildResponse(BaseModel):
    job_id: str


class Node(BaseModel):
    """One node of the clause tree L0 parsed from a document (`GET /documents/{doc_id}/nodes`)."""

    node_id: str
    parent_id: str | None = None
    kind: str
    number: str | None = Field(default=None, description="the marker as printed: a clause number or a label like (a)")
    title: str | None = None
    page: int | None = None
    box: list[float] | None = Field(default=None, min_length=4, max_length=4, description="[x0, y0, x1, y1] of the marker, PDF points")


class EvaluateRequest(BaseModel):
    version: int | None = Field(default=None, description="a confirmed rule-set version; default: the latest confirmed")


class JobStarted(BaseModel):
    job_id: str


class ReasonBody(BaseModel):
    """The body of a DELETE or a gap PATCH: why."""

    reason: str = Field(min_length=1)


class NotePatch(BaseModel):
    """`PATCH /ruleset/items/{letter}/notes/{i}`: the note as it should read, and why."""

    note: ItemNote
    reason: str = Field(min_length=1)


# ---------------------------------------------------------------- S4-4: pricing, evaluation, reports
class PriceSchemeOut(BaseModel):
    """The tender's price scheme as the confirmed rule set states it."""

    type: Literal["cost_effectiveness", "unit_price_x_quantity"]
    quantity: float | None = Field(default=None, description="the estimated quantity, from the price schedule item's slot")
    unit: str = "kg"
    currency: str | None = Field(default=None, description="the tender's currency as the summary prints it (e.g. HK$, US$, €); "
                                                           "null when it is not set and the offers are not all in one currency")
    base_currency: str | None = Field(default=None, description="the same currency as an ISO 4217 code")
    exchange_rates: dict[str, float] = Field(default_factory=dict, description="ISO code -> the rate that converts a price "
                                                                               "in that currency into the tender's currency")
    currency_source: str = Field(default="", description="where the tender's currency came from: a rule-set slot, "
                                                         "PRICING_BASE_CURRENCY, or every offer being quoted in it")
    source: str = Field(default="", description="where the quantity came from")


class PriceRow(BaseModel):
    tenderer: str
    run_id: str
    conforming: bool = Field(description="Stage I and II both pass")
    currency: str = Field(description="the offer's currency as the summary prints it, or as the offer printed it when "
                                      "it is not recognised")
    unit_price: float | None = Field(default=None, description="as quoted, in the offer's currency")
    unit_price_base: float | None = Field(default=None, description="in the tender's currency; null when it cannot be "
                                                                    "converted, and the remark says why")
    dosage: float | None = None
    dosage_rounded: float | None = Field(default=None, description="two significant figures, per the Terms of Tender")
    estimated_goods_price: float | None = None
    quoted_total: float | None = None
    arithmetic_ok: bool | None = None
    cost_effectiveness: float | None = None
    ranking: int | None = None
    remark: str = ""
    stage1: str | None = None
    stage2: str | None = None
    reviewed_by: str | None = None
    corrected: list[str] = Field(default_factory=list, description="price fields a reviewer corrected")


class PriceSummary(BaseModel):
    ruleset_version: int
    scheme: PriceSchemeOut
    rows: list[PriceRow]
    recommended: str | None = Field(default=None, description="the best-ranked conforming offer")
    missing: list[str] = Field(default_factory=list, description="tenderers whose result is at another rule-set version")


class TendererEvaluation(BaseModel):
    tenderer: str
    run_id: str
    stage1: str | None
    stage2: str | None
    items: dict[str, str]
    reviewed_by: str | None = None
    corrections: int = 0
    conforming: bool


class Evaluation(BaseModel):
    ruleset_version: int
    tenderers: list[TendererEvaluation]
    stage1_conclusion: str
    stage2_conclusion: str
    recommendation: str
    recommended: str | None = None
    price: PriceSummary


class ReportInfo(BaseModel):
    name: str
    version: int
    generated_at: datetime | None = Field(default=None, description="null until first downloaded")
    approver: str | None = Field(default=None, description="who confirmed the reviews the report rests on")

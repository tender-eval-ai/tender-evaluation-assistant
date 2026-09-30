"""Data contracts for every pipeline stage.

The LLM-facing models (Rubric, BidExtraction) double as the JSON schema sent to the
model, so extraction output is validated at the boundary and retried on mismatch.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, Field


# ---------------------------------------------------------------- rubric (stage 2 of pipeline)

class ChecklistItem(BaseModel):
    """One Stage I completeness item (a form/schedule/certificate that must be present)."""
    id: str = Field(description="Stable id, e.g. 'S1-01'")
    item: str = Field(description="What must be submitted, e.g. 'Signed Tender Form (G.F.230)'")
    source_clause: str = Field(default="", description="Quoted clause requiring it")
    source_file: str = Field(default="", description="Tender file (### FILE header) stating it")
    source_page: Optional[int] = Field(default=None, description="[Page N] marker where stated")
    required: bool = True


class EssentialRequirement(BaseModel):
    """One Stage II essential requirement (non-compliance disqualifies the offer)."""
    id: str = Field(description="Stable id, e.g. 'S2-01'")
    requirement: str
    source_clause: str = ""
    source_file: str = Field(default="", description="Tender file (### FILE header) stating it")
    source_page: Optional[int] = Field(default=None, description="[Page N] marker where stated")


class PriceScheme(BaseModel):
    """How the tender says price must be assessed. Drives which Price Summary format is used."""
    type: Literal["cost_effectiveness", "unit_price_x_quantity"]
    quantity: float = Field(description="Estimated quantity from the Price Schedule")
    unit: str = "kg"
    currency: str = "HKD"
    notes: str = ""
    source_file: str = Field(default="", description="Tender file (### FILE header) defining the scheme")
    source_page: Optional[int] = Field(default=None, description="[Page N] marker where defined")


class Rubric(BaseModel):
    """The evaluation rubric derived from one tender's documents. Saved as rubric.json
    for human confirmation before evaluation runs."""
    tender_ref: str
    subject: str = ""
    stage1_checklist: list[ChecklistItem]
    stage2_requirements: list[EssentialRequirement]
    price_scheme: PriceScheme


# ---------------------------------------------------------------- per-bid extraction

class DocumentPresence(BaseModel):
    checklist_id: str
    present: bool
    page: Optional[int] = Field(default=None, description="Page in the bid where found")
    note: str = ""


class ComplianceFinding(BaseModel):
    requirement_id: str
    complies: Literal["yes", "no", "unclear"]
    evidence: str = Field(default="", description="Short quote or observation supporting the finding")
    page: Optional[int] = None


class BidPrice(BaseModel):
    currency: str = "HKD"
    unit_price: Optional[float] = Field(default=None, description="One-time unit price as quoted")
    optimal_dosage: Optional[float] = Field(
        default=None, description="Optimal dosage, only for cost-effectiveness schemes")
    quoted_total: Optional[float] = Field(
        default=None, description="Estimated goods price as quoted by the tenderer, if stated")
    # Stored before F6 as `fx_to_hkd`; read under either name, so an old extraction
    # or checkpoint keeps its rate instead of pricing a foreign bid at 1.0.
    fx_to_base: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("fx_to_base", "fx_to_hkd"),
        description="Conversion rate to the base currency if quoted in a foreign currency")


class BidExtraction(BaseModel):
    """Everything extracted from one tenderer's offer."""
    tenderer: str
    documents: list[DocumentPresence]
    compliance: list[ComplianceFinding]
    price: BidPrice
    source_file: str = ""


# ---------------------------------------------------------------- evaluation results

class Stage1Result(BaseModel):
    tenderer: str
    presence: dict[str, DocumentPresence]  # checklist_id -> finding
    missing: list[str]                     # checklist ids of required items not present
    passed: bool


class Stage2Result(BaseModel):
    tenderer: str
    findings: dict[str, ComplianceFinding]  # requirement_id -> finding
    non_compliant: list[str]                # requirement ids judged "no"
    unclear: list[str]                      # requirement ids judged "unclear"
    passed: bool


class PriceRow(BaseModel):
    tenderer: str
    conforming: bool                        # passed Stage I and Stage II
    currency: str = "HKD"
    unit_price: Optional[float] = None      # as quoted, original currency
    unit_price_base: Optional[float] = Field(default=None, validation_alias=AliasChoices("unit_price_base", "unit_price_hkd"))
    dosage: Optional[float] = None
    dosage_rounded: Optional[float] = None  # 2 significant figures per the tender formula
    estimated_goods_price: Optional[float] = None  # HKD
    quoted_total: Optional[float] = None
    arithmetic_ok: Optional[bool] = None    # quoted total tallies with unit price x quantity
    cost_effectiveness: Optional[float] = None
    ranking: Optional[int] = None
    remark: str = ""


class EvaluationResult(BaseModel):
    rubric: Rubric
    stage1: list[Stage1Result]
    stage2: list[Stage2Result]
    price_rows: list[PriceRow]
    recommended: Optional[str] = None       # best-ranked conforming tenderer
    stage1_conclusion: str = ""
    stage2_conclusion: str = ""

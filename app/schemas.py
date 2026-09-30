"""The price engine's models (`app/pricing.py`), from the prototype's pipeline.

The vendor check's pricing (`app/checks/pricing.py`) fills a `BidExtraction` with only the
price; the prototype's rubric and evaluation models went with it at S5.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, Field


# ---------------------------------------------------------------- the tender's price scheme

class PriceScheme(BaseModel):
    """How the tender says price must be assessed. Drives which Price Summary format is used."""
    type: Literal["cost_effectiveness", "unit_price_x_quantity"]
    quantity: float = Field(description="Estimated quantity from the Price Schedule")
    unit: str = "kg"
    currency: str = "HKD"
    notes: str = ""
    source_file: str = Field(default="", description="Tender file (### FILE header) defining the scheme")
    source_page: Optional[int] = Field(default=None, description="[Page N] marker where defined")


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


# ---------------------------------------------------------------- the Price Summary

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

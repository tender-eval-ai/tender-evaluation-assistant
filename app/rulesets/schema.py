"""Shared contract for rule sets (agreed at stop point S0).

The rule builder (L1-L4) writes these models, the rule engine (V6) reads them, and the
Rules window (L5) edits them. Both engineers import from here and nowhere else. A change
to this file goes through its own pull request labelled `contract` with both approvals,
and every stored result is pinned to the `RuleSet.version` it was computed against.

Design rules the models enforce:
- Every value the model extracted carries a Citation with a verbatim quote; code, not the
  model, sets `verified` after checking that the quote is on the cited node and that the
  value appears in the quote.
- The LLM may only choose a check from the twelve `CheckType` kinds; anything else is
  `human_only`, and a person decides.
- A rule set cannot be confirmed while an item still needs input or a gap has no reason.
- Human edits keep the model's value next to the correction and record who, when and why.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class DataClass(StrEnum):
    """Who may see the text. The LLM gateway refuses to send anything but `synthetic`
    to an endpoint that is not on the allowlist for its class."""

    SYNTHETIC = "synthetic"                # generated fixtures; may go anywhere
    REDACTED_SAMPLE = "redacted_sample"    # the camp's redacted cases; cleared endpoints only, by explicit decision
    CONFIDENTIAL = "confidential"          # real client documents; never leave the approved environment


class CheckType(StrEnum):
    """The only menu of checks a rule may use. Twelve kinds; a short fixed menu is what
    makes an LLM-drafted rule checkable by code."""

    FILLED = "filled"                            # the field has a value
    VALUE = "value"                              # equals an expected value (usually from a slot)
    RANGE = "range"                              # number within [min, max]
    UNIT = "unit"                                # the unit of measure matches
    DATE = "date"                                # a date parses and is before/after a bound
    MATH = "math"                                # an arithmetic relation between fields holds
    TICK_BOX = "tick_box"                        # a box is ticked
    SIGNATURE = "signature"                      # signed (and dated when required)
    DOCUMENT_PRESENT = "document_present"        # the document exists in the bid
    CROSS_DOCUMENT_MATCH = "cross_document_match"  # the same value appears in two documents
    CONTAINS = "contains"                        # text contains a phrase
    HUMAN_ONLY = "human_only"                    # no automated check; a reviewer decides


class Tier(StrEnum):
    """Consequence of a missing item, from the Completeness Check Schedule's Parts."""

    A = "A"  # missing: the tender is not considered further
    B = "B"  # missing: the Authority may request it before disqualifying
    C = "C"  # discretionary: may be requested later or evaluated as submitted


class SlotKind(StrEnum):
    NUMBER = "number"
    TEXT = "text"
    LIST = "list"
    DATE = "date"
    MONEY = "money"


class ItemStatus(StrEnum):
    VERIFIED = "verified"        # template matched, every required slot filled and verified
    NEEDS_INPUT = "needs_input"  # a required slot is empty or unverified; blocks confirmation
    NOVEL = "novel"              # no template; rules drafted from the clause (L3), person must approve
    GAP = "gap"                  # the item is in the schedule but no rule could be built
    EDITED = "edited"            # a person changed something; the model's version is kept alongside


class Citation(BaseModel):
    """Where a value or a rule comes from. `quote` is verbatim; `node_id` is the clause
    node from the parser (e.g. "Supp:13:(a)") or None for a page-level citation when the
    document's structure was too messy to trust."""

    file: str = Field(description="path relative to the project, e.g. 'tender/09 Schedules.pdf'")
    page: int = Field(ge=1)
    node_id: str | None = None
    quote: str = Field(min_length=1)
    data_class: DataClass


class Edit(BaseModel):
    """Who changed something, when and why. Required on every human change."""

    by: str
    at: datetime
    reason: str = Field(min_length=1)


class SlotSpec(BaseModel):
    """A parameter a template needs from the tender, e.g. the estimated quantity."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", description="identifier used as {name} in TemplateRule.params")
    kind: SlotKind
    unit: str | None = None
    required: bool = True
    description: str = Field(min_length=1, description="what to look for, one sentence the LLM reads")


class SlotValue(BaseModel):
    """A filled slot. An extracted value must cite its source; `verified` is set only by
    code. When a person corrects it, `origin` becomes manual, `model_value` keeps what the
    model said, and `edit` records the change."""

    value: Any | None = None
    citation: Citation | None = None
    verified: bool = False
    origin: Literal["extracted", "manual"] = "extracted"
    model_value: Any | None = None
    edit: Edit | None = None

    @model_validator(mode="after")
    def _extracted_values_cite_their_source(self) -> SlotValue:
        if self.value is not None and self.origin == "extracted" and self.citation is None:
            raise ValueError("an extracted slot value must carry a citation")
        if self.verified and self.citation is None:
            raise ValueError("a value without a citation cannot be verified")
        if self.origin == "manual" and self.edit is None:
            raise ValueError("a manual value must record who set it and why")
        return self


class TemplateRule(BaseModel):
    """One check the engine runs on one vendor field. `params` reference slots as
    "{slot_name}" or hold literals; the engine renders them per tender."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_.]*$", description="e.g. 'price_schedule.unit_price_present'")
    check: CheckType
    field: str = Field(min_length=1, description="vendor field, e.g. 'price_schedule.unit_price'")
    params: dict[str, str] = Field(default_factory=dict)
    tier: Tier
    condition: str | None = Field(default=None, description="applies only when this holds, e.g. 'not manufacturer'")
    depends_on: list[str] = Field(default_factory=list, description="rule ids that must pass first")
    note: str | None = None


class Gap(BaseModel):
    """A clause the schedule points to, or a 'shall/must' sentence, that no rule covers.
    A gap blocks confirmation until a person gives a reason."""

    node_id: str
    text: str
    reason: str | None = None


class RuleSetItem(BaseModel):
    """One Completeness Check Schedule item, (a) to (o), with its rules."""

    letter: str = Field(pattern=r"^[a-z]$")
    title: str = Field(min_length=1)
    part: Tier
    template: str | None = Field(default=None, description="template id; None for a novel item")
    citation: Citation = Field(description="the schedule row")
    clauses: list[Citation] = Field(default_factory=list, description="the clauses the row points to")
    slots: dict[str, SlotValue] = Field(default_factory=dict)
    rules: list[TemplateRule] = Field(default_factory=list)
    status: ItemStatus
    edit: Edit | None = None

    @model_validator(mode="after")
    def _rule_ids_unique(self) -> RuleSetItem:
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate rule ids in item ({self.letter})")
        return self


class RuleSet(BaseModel):
    """A versioned rule set for one project. Draft until a person confirms it; editing a
    confirmed set opens a new draft whose `parent_version` is the confirmed one."""

    project_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    parent_version: int | None = None
    status: Literal["draft", "confirmed"] = "draft"
    data_class: DataClass
    items: list[RuleSetItem]
    gaps: list[Gap] = Field(default_factory=list)
    created_by: str
    created_at: datetime
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    model: str | None = Field(default=None, description="model that drafted it, e.g. 'deepseek-v4-flash'")
    prompt_version: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> RuleSet:
        letters = [i.letter for i in self.items]
        if len(letters) != len(set(letters)):
            raise ValueError("item letters must be unique")
        if self.parent_version is not None and self.parent_version >= self.version:
            raise ValueError("parent_version must be older than version")
        if self.status == "confirmed":
            if not self.confirmed_by or not self.confirmed_at:
                raise ValueError("a confirmed rule set records who confirmed it and when")
            blocking = [i.letter for i in self.items if i.status in (ItemStatus.NEEDS_INPUT, ItemStatus.GAP)]
            if blocking:
                raise ValueError(f"items still need input or are gaps: {blocking}")
            unexplained = [g.node_id for g in self.gaps if not g.reason]
            if unexplained:
                raise ValueError(f"gaps without a reason: {unexplained}")
        return self

    def item(self, letter: str) -> RuleSetItem:
        for i in self.items:
            if i.letter == letter:
                return i
        raise KeyError(letter)


CHECK_TYPES: frozenset[CheckType] = frozenset(CheckType)
assert len(CHECK_TYPES) == 12, "the check menu is exactly twelve kinds; changing it is a contract change"

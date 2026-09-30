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
- A rule is a gate: it names a consequence tier, or carries its own outcomes. Notes,
  definitions and triggers are `ItemNote`s, not rules.
- Outcome keys come from one closed vocabulary shared with the engine, so a misspelt key
  fails validation instead of never matching.
- A rule set cannot be confirmed while an item still needs input or a gap has no reason.
- Human edits keep the model's value next to the correction and record who, when and why.

S0 amendments (2026-09-17, from docs/check_kind_mapping.md "Schema gaps"): outcomes per
result, seven consequence tiers on a rule while A/B/C stays the schedule Part on an item,
normalisation steps, typed params, a stage per rule, item notes and conditions, ids for
added items, and the template file format with its per-template consequence defaults.
"""
from __future__ import annotations

import hashlib
import json
import re
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


class Part(StrEnum):
    """The Completeness Check Schedule's Parts: what a missing item means for the tender."""

    A = "A"  # missing: the tender is not considered further
    B = "B"  # missing: the Authority may request it before disqualifying
    C = "C"  # discretionary: may be requested later or evaluated as submitted


class Consequence(StrEnum):
    """What a blank or failing field means for one rule, before any rule-level override.
    The seven tiers the rule files use. The default outcomes for a tier are defined per
    template (`Template.consequences`), because they differ from form to form."""

    CRITICAL = "critical"                          # blank: disqualified; redacted: needs_review
    MANDATORY_ON_REQUEST = "mandatory_on_request"  # blank: dormant, may be requested later
    ON_REQUEST_ONLY = "on_request_only"            # not requested: dormant; requested and missed: disqualified
    DEEMED_COMPLIANCE = "deemed_compliance"        # blank: pass; expressly non-compliant: disqualified
    DEEMED_DEFAULT = "deemed_default"              # blank: pass, read as the stated default (e.g. cash)
    DISCRETIONARY = "discretionary"                # blank: pass; the Authority may ask later
    NO_GATE = "no_gate"                            # recorded, never changes the verdict


class SlotKind(StrEnum):
    NUMBER = "number"
    TEXT = "text"
    LIST = "list"
    DATE = "date"
    MONEY = "money"


class ItemStatus(StrEnum):
    VERIFIED = "verified"        # template matched, every required slot filled and verified
    NEEDS_INPUT = "needs_input"  # a required slot is empty or unverified, or the item is located
                                 # (L0) with no rules yet; blocks confirmation
    NOVEL = "novel"              # no template; rules drafted from the clause (L3), person must approve
    GAP = "gap"                  # the item is in the schedule but no rule could be built
    EDITED = "edited"            # a person changed something; the model's version is kept alongside.
                                 # An item a person adds is `edited` with its edit record (I1.16)


OutcomeStatus = Literal["pass", "needs_review", "disqualified", "dormant"]

# The outcome vocabulary. For each evaluated rule the engine picks one key: the field's
# presence state, or the first positive / negative / neutral key the rule's outcomes define
# (app/engine/core.py keeps the same three tables; test/test_rulesets_schema.py proves they
# match). Closed on purpose: a new pair is one line here, in a `contract` PR.
PRESENCE_KEYS: frozenset[str] = frozenset({"blank", "filled", "redacted", "not_applicable"})
POSITIVE_KEYS: frozenset[str] = frozenset({
    "match", "within_range", "within_precision", "valid", "compliant", "confirmed_compliant",
    "accredited", "on_time", "requested_and_met", "content_ok", "complete", "sealed",
    "bundled", "not_a_postal_box", "no_extra_charges", "receipt_confirmed",
    "effective_and_not_aborted",
})
NEGATIVE_KEYS: frozenset[str] = frozenset({
    "mismatch", "outside_range", "exceeds_precision", "invalid", "non_compliant", "noncompliant",
    "expressly_non_compliant", "not_accredited", "late", "requested_and_missed", "content_wrong",
    "incomplete", "not_sealed", "not_bundled", "postal_box", "extra_charges_proposed",
    "no_receipt_evidence", "not_effective_or_aborted",
})
NEUTRAL_KEYS: frozenset[str] = frozenset({"not_applicable", "not_requested", "unstated", "na"})
OUTCOME_KEYS: frozenset[str] = PRESENCE_KEYS | POSITIVE_KEYS | NEGATIVE_KEYS | NEUTRAL_KEYS

_SLOT_REF = re.compile(r"^\{([a-z][a-z0-9_]*)\}$")

ParamValue = str | int | float | bool | list[str]


class Citation(BaseModel):
    """Where a value or a rule comes from. `quote` is verbatim; `node_id` is the clause
    node from the parser (e.g. "Supp:13:(a)") or None for a page-level citation when the
    document's structure was too messy to trust."""

    file: str = Field(description="path relative to the project, e.g. 'tender/09 Schedules.pdf'")
    page: int = Field(ge=1)
    node_id: str | None = None
    candidates: list[str] | None = Field(default=None, description="when the resolver matched several nodes: "
                                         "every node id it found; node_id is the one chosen, a person may pick another")
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


class FollowUp(BaseModel):
    """What a dormant outcome leads to: what triggers the request, by when the tenderer
    must answer (prose, always present) and what a missed deadline means."""

    trigger: str = Field(min_length=1)
    deadline: str = Field(min_length=1)
    if_deadline_missed: OutcomeStatus


class Outcome(BaseModel):
    """The verdict for one outcome key. `note` may use {field} for the field's label."""

    status: OutcomeStatus
    note: str | None = None
    follow_up: FollowUp | None = None

    @model_validator(mode="after")
    def _follow_up_only_when_dormant(self) -> Outcome:
        if self.follow_up is not None and self.status != "dormant":
            raise ValueError("a follow_up belongs to a dormant outcome only")
        return self


def _check_outcome_keys(outcomes: dict[str, Outcome], where: str) -> None:
    unknown = sorted(set(outcomes) - OUTCOME_KEYS)
    if unknown:
        raise ValueError(f"{where}: unknown outcome keys {unknown}; the vocabulary is closed (OUTCOME_KEYS)")


class Normalise(BaseModel):
    """A step applied to the field's value before the rule's checks, by the engine's own
    name; a rule's steps run in order. `round_significant_figures` takes `max_sig_figs`, a
    whole number from 1; `resolve_range_to_lower_bound` takes nothing."""

    op: Literal["round_significant_figures", "resolve_range_to_lower_bound"]
    # bool first, so `true` stays a bool the check below refuses instead of becoming 1 (#117).
    params: dict[str, bool | str | int | float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _params_fit_the_op(self) -> Normalise:
        if self.op == "round_significant_figures":
            figures = self.params.get("max_sig_figs")
            if set(self.params) != {"max_sig_figs"} or not isinstance(figures, int) or isinstance(figures, bool) \
                    or figures < 1:
                raise ValueError("round_significant_figures takes one param, max_sig_figs: a whole number from 1")
        elif self.params:
            raise ValueError(f"{self.op} takes no params")
        return self


class TemplateRule(BaseModel):
    """One check the engine runs on one vendor field. `params` hold literals or reference
    slots as "{slot_name}"; the engine renders them per tender. A rule is a gate: it names
    the consequence tier whose template defaults apply, or carries its own `outcomes`,
    which replace the tier's defaults whole."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_.]*$", description="e.g. 'price_schedule.unit_price_present'")
    check: CheckType
    field: str = Field(min_length=1, description="vendor field, e.g. 'price_schedule.unit_price'")
    params: dict[str, ParamValue] = Field(default_factory=dict)
    consequence: Consequence | None = None
    outcomes: dict[str, Outcome] | None = None
    normalise: list[Normalise] = Field(default_factory=list)
    stage: Literal["I", "II"] = "I"
    condition: str | None = Field(default=None, description="applies only when this holds, e.g. 'not manufacturer'")
    depends_on: list[str] = Field(default_factory=list,
                                  description="rule ids that must pass first; the engine also accepts one id")
    note: str | None = None

    @model_validator(mode="after")
    def _is_a_gate(self) -> TemplateRule:
        if self.consequence is None and self.outcomes is None:
            raise ValueError(f"rule {self.id} needs a consequence or its own outcomes; a note belongs in ItemNote")
        if self.outcomes is not None:
            _check_outcome_keys(self.outcomes, f"rule {self.id}")
        # `blank_if` lists the answers that mean "nothing" ("Nil", "None"); a string, or an empty
        # entry, would be ignored without a word (#117).
        empty = self.params.get("blank_if")
        if empty is not None and (not isinstance(empty, list) or not empty or not all(isinstance(w, str) and w.strip() for w in empty)):
            raise ValueError(f"rule {self.id}: blank_if is a list of answers that mean nothing, e.g. [\"nil\", \"none\"]")
        return self

    def slot_refs(self) -> set[str]:
        """Slot names this rule's params reference as "{name}"."""
        refs = set()
        for value in self.params.values():
            if isinstance(value, str) and (m := _SLOT_REF.match(value)):
                refs.add(m.group(1))
        return refs


class FollowUpDeadline(BaseModel):
    """How the engine turns a dormant outcome's prose deadline into a date, from the
    request date it is given at check time."""

    op: Literal["add_working_days", "add_calendar_days"]
    offset: int = Field(ge=1)


class ItemNote(BaseModel):
    """Prose attached to an item that is not a check: a definition, what triggers a
    requirement, a consequence stated in the clause, or a cross-reference."""

    kind: Literal["definition", "trigger", "consequence", "reference"]
    text: str = Field(min_length=1)
    citation: Citation | None = None


class ConsequenceDefaults(BaseModel):
    """A template's default outcomes for one consequence tier."""

    outcomes: dict[str, Outcome]
    follow_up_deadline: FollowUpDeadline | None = None

    @model_validator(mode="after")
    def _keys_closed(self) -> ConsequenceDefaults:
        _check_outcome_keys(self.outcomes, "consequence defaults")
        return self


class Template(BaseModel):
    """One form's reusable rules, stored as app/rulesets/templates/<id>.json. A rule set
    item that matched a template (L1) copies its rules and fills its slots from the tender
    (L2); the engine reads `consequences` for every rule that names a tier."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    form_name: str = Field(min_length=1)
    slots: list[SlotSpec] = Field(default_factory=list)
    consequences: dict[Consequence, ConsequenceDefaults] = Field(default_factory=dict)
    # The form's own prose and trigger, inherited by every item that matches it. A
    # definition of a term the form uses, or a trigger such as "needed only when the
    # tenderer does not make the goods itself", is a fact about the FORM: it holds
    # for every tender that uses it. Held only on the item, each tender would have to
    # rediscover it, which is what the library exists to prevent. An item may
    # override `condition`; it never loses the template's notes.
    notes: list[ItemNote] = Field(default_factory=list)
    condition: str | None = Field(default=None, description="the form applies only when this holds")
    rules: list[TemplateRule]

    @model_validator(mode="after")
    def _consistent(self) -> Template:
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate rule ids in template {self.id}")
        slots = {s.name for s in self.slots}
        for r in self.rules:
            if r.consequence is not None and r.outcomes is None and r.consequence not in self.consequences:
                raise ValueError(f"rule {r.id} names tier {r.consequence} but template {self.id} has no defaults for it")
            missing = r.slot_refs() - slots
            if missing:
                raise ValueError(f"rule {r.id} references slots {sorted(missing)} the template does not declare")
        return self


    def content_hash(self) -> str:
        """The first 12 hex digits of the SHA-256 of the template's content: which template, as
        it was, an item came from (#89). A copy of it is what gets evaluated."""
        text = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(text.encode()).hexdigest()[:12]

    def copy_for(self) -> TemplateCopy:
        """What an item keeps of this template once L1 has matched it: the slot specs, every
        tier the template defines, and the content hash. Every tier, not only those the rules
        name: a reviewer may later move a rule to another tier, or add one, and the item must
        still hold its outcomes (#136 review). The Part re-tier changes which tier a rule
        names, not what the tiers say, so the copy holds it either way."""
        return TemplateCopy(version=self.content_hash(), slots=[s.model_copy(deep=True) for s in self.slots],
                            consequences={t: d.model_copy(deep=True) for t, d in self.consequences.items()})


class TemplateCopy(BaseModel):
    """What an item took from its template when it was matched (#89): the slot specs, the
    template's consequence tiers, and its content hash. Evaluation, the slot
    fill (L2) and confirmation read this copy, so a later change to the template never alters
    an item already built; an item stored before the copy existed reads the library, as before."""

    version: str = Field(pattern=r"^[0-9a-f]{12}$", description="Template.content_hash() when the item was matched")
    slots: list[SlotSpec] = Field(default_factory=list)
    consequences: dict[Consequence, ConsequenceDefaults] = Field(default_factory=dict)


class Gap(BaseModel):
    """A clause the schedule points to, or a 'shall/must' sentence, that no rule covers.
    A gap blocks confirmation until a person gives a reason."""

    node_id: str
    text: str
    reason: str | None = None
    edit: Edit | None = Field(default=None, description="who gave the reason, when and why")


class PartSpec(BaseModel):
    """A Part's intro in the Completeness Check Schedule: the paragraph that says what
    happens when an item of that Part is missing or asked for, and the clauses it cites.
    Located by L0; the engine reads the consequence from the Part."""

    part: Part
    title: str = Field(min_length=1)
    citation: Citation = Field(description="the Part's heading and intro paragraph")
    clauses: list[Citation] = Field(default_factory=list, description="the clauses the intro points to")


class RuleSetItem(BaseModel):
    """One Completeness Check Schedule item, (a) to (o), with its rules. An item a person
    adds has no schedule letter and is numbered x1, x2, ..."""

    letter: str = Field(pattern=r"^([a-z]|x[1-9][0-9]*)$")
    title: str = Field(min_length=1)
    part: Part
    template: str | None = Field(default=None, description="template id; None for a novel item")
    template_copy: TemplateCopy | None = Field(
        default=None, description="what the item took from its template when matched (#89); null before, or for a novel item")
    citation: Citation = Field(description="the schedule row")
    clauses: list[Citation] = Field(default_factory=list, description="the clauses the row points to")
    condition: str | None = Field(default=None, description="the item applies only when this holds")
    notes: list[ItemNote] = Field(default_factory=list)
    slots: dict[str, SlotValue] = Field(default_factory=dict)
    rules: list[TemplateRule] = Field(default_factory=list)
    status: ItemStatus
    edit: Edit | None = None

    @model_validator(mode="after")
    def _rules_consistent(self) -> RuleSetItem:
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate rule ids in item ({self.letter})")
        if self.template is None:
            without = [r.id for r in self.rules if r.outcomes is None]
            if without:
                raise ValueError(f"item ({self.letter}) has no template, so its rules need their own outcomes: {without}")
            if self.template_copy is not None:
                raise ValueError(f"item ({self.letter}) has no template, so it keeps no copy of one")
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
    parts: list[PartSpec] = Field(default_factory=list, description="the Part intros the items sit under")
    gaps: list[Gap] = Field(default_factory=list)
    created_by: str
    created_at: datetime
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    updated_by: str | None = Field(default=None, description="who last saved this draft; server-owned, read-only")
    model: str | None = Field(default=None, description="model that drafted it, e.g. 'deepseek-v4-flash'")
    prompt_version: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> RuleSet:
        letters = [i.letter for i in self.items]
        if len(letters) != len(set(letters)):
            raise ValueError("item letters must be unique")
        parts = [p.part for p in self.parts]
        if len(parts) != len(set(parts)):
            raise ValueError("each Part appears once in parts")
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

from dataclasses import dataclass

# Shared per-field/row output shape across every checker in this package, so one
# frontend table component can render results from any of them without
# per-checker-type branching. Design trail and rationale: plan.md "Unified
# checker output shape: FieldResult" (2026-08-06).
#
# A field that passes still carries "source" - a reviewer double-checking a
# pass ("why is HK$ acceptable here?") needs the same citation trail as one
# disputing a failure, it just isn't surfaced by default.
#
# Distinct from HumanCheckFlag (tender_term_form_validator.py): that represents
# a note from the vision model's own human_checks (e.g. "confirm this wasn't
# photocopied") which has no extracted value or pass/fail state of its own -
# nothing to hang a FieldResult off of. This type is for things checked against
# a specific field's value.
@dataclass
class FollowUp:
    trigger: str
    deadline: str  # prose fallback ("5 working days from the request") - always present
    if_deadline_missed: str
    # Concrete ISO date, only populated when a tier's follow_up_deadline transform
    # can actually run (the item supplies a real trigger date to compute from).
    # `deadline` stays the always-present prose description either way - this is
    # additive, not a replacement, so a reviewer still has something to read even
    # when no trigger date is known yet.
    computed_deadline: str | None = None


@dataclass
class FieldResult:
    field_id: str  # stable machine key (e.g. "estimated_quantity") - use this to
    # look up/match a field programmatically; "field" below is display text and
    # may be reworded without warning.
    field: str
    value: object
    status: str  # "pass" | "disqualified" | "needs_review" | "dormant"
    confidence: float | None
    source: str | None
    note: str | None
    follow_up: FollowUp | None = None  # only ever set when status == "dormant"
    # Structured signal, not just prose in `note`: "value is null" means the same
    # thing whether a field is genuinely blank or filled-but-redacted, and
    # "needs_review" alone covers both redaction and unrelated data-quality
    # issues (e.g. a unit mismatch) - a frontend needs this to pick the right
    # treatment (a redaction-bar affordance vs. a warning icon) without string-
    # matching `note` for the word "redacted". Found by building the review-
    # panel mockup (plan.md "Unified checker output shape") and confirmed real:
    # every checker that models redaction (tender_term_form_validator,
    # particulars_of_goods_schedule_checker) had `value: null` and a prose-only
    # explanation for it before this field existed.
    redacted: bool = False
    # "I" (presence/completeness) | "II" (essential-requirements adequacy) -
    # resolved by the engine from the rule's own "stage" key, falling back to
    # the rules document's "default_stage" (see engine/core.py). Needed so a
    # frontend can group one checker's output by stage without maintaining its
    # own copy of which rule ids are which - the JSON is still the only source
    # of truth, this just carries the resolved answer through to the output
    # instead of leaving it as unconsumed rule metadata (the same "if_not_met
    # was never read" gap docs/stage1_rules_rubric.md §2 already found once).
    stage: str = "I"


# Fixed copy for each status, so wording stays consistent across every checker's
# output and every place it's displayed, instead of each frontend screen (or
# each new checker written later) inventing its own phrasing.
STATUS_LABELS = {
    "pass": "Compliant",
    "disqualified": "Disqualifying — Tender not considered further",
    "needs_review": "Needs human review",
    "dormant": "Not yet required — may be requested by the Authority later",
}

# Rank for picking the worst outcome when more than one issue applies to the same
# field (e.g. a Price Schedule row with both a blank Unit Price and a rejected
# currency on what was typed) - higher wins.
_STATUS_SEVERITY = {"pass": 0, "dormant": 1, "needs_review": 2, "disqualified": 3}


def worst_status(statuses: list[str]) -> str:
    return max(statuses, key=lambda s: _STATUS_SEVERITY[s], default="pass")


def build_field_result(
    field_id: str,
    field: str,
    value,
    confidence: float | None,
    source: str | None,
    issues: list[tuple[str, str]],
    follow_up: FollowUp | None = None,
    redacted: bool = False,
    stage: str = "I",
) -> FieldResult:
    # Shared by every checker: a field can fail more than one rule at once (e.g.
    # a Price Schedule Unit Price that's both blank AND has an invalid currency
    # typed in) - issues is the full list of (status, note) pairs found, the
    # worst status wins, and every note is kept, not just the first. Pass
    # follow_up whenever a "dormant" issue might be among them; it's only kept
    # on the result if dormant actually wins.
    status = worst_status([s for s, _ in issues]) if issues else "pass"
    note = "; ".join(n for _, n in issues) or None
    return FieldResult(
        field_id=field_id,
        field=field,
        value=value,
        status=status,
        confidence=confidence,
        source=source,
        note=note,
        follow_up=follow_up if status == "dormant" else None,
        redacted=redacted,
        stage=stage,
    )


def status_counts(fields: list[FieldResult]) -> dict[str, int]:
    counts = dict.fromkeys(_STATUS_SEVERITY, 0)
    for field in fields:
        counts[field.status] += 1
    return counts


def overall_status(fields: list[FieldResult]) -> str:
    # Rolls up to a single top-line verdict for the whole item/form, so a
    # reviewer or dashboard doesn't have to scan every field to know whether
    # anything needs attention. Dormant fields never affect this - "may be
    # requested later" isn't a problem with the tender as submitted today.
    return worst_status([f.status for f in fields if f.status != "dormant"])

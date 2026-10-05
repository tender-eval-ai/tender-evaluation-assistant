"""V6: a RuleSet from the shared contract evaluated by Nasi's rule engine, every item.

The engine reads a rules document in its own JSON vocabulary (rules with an id, a
field_id, a consequence tier or their own outcomes, depends_on, stage) and a vendor
item: flat keys, `<field>_redacted` and `<field>_confidence` beside each value. This
module is the only place that translates between the two, so the rule split at S1 and
the engine stay untouched by each other.

Since S4-3 it decides every item of the rule set (`decide`): the comparison kinds of the
closed CheckType menu (value, range, unit, date, math, cross-document match, contains) are
computed here in code and handed to the engine as explicit outcomes; `{slot}` references
in a rule's params are rendered from the item's slots; a rule on a field no form reads is a
reviewer's call, never a blank; V4's unverified values are `needs_review`; and the Stage I
and II summaries roll up from the rules' stages.

Since J12: `contains` takes `phrases` (all must be there) and `absent` (none may be);
`range` takes `max_decimals` (every figure as written); a rule's `normalise` steps run
here, in order, on the field's value before any rule of the item reads it, and what they
changed is reported under `adjustments` (internal: not in the API's Verdict); and a blank
field a reviewer enters (`FieldDef.by`) is dormant, with a row to enter it on, whatever the
rule's outcomes say. A `human_only` check on a blank field waits for the field, and a date
bound that is not a date is a reviewer's call, never skipped.

For the production templates (J12): a rule naming a tier its template does not define
makes the item a reviewer's call, like a missing template, never a silent pass; a rule
whose params use an optional slot the tender left empty does not apply; and a rule's
`blank_if` param lists answers that mean "nothing" ("Nil", "None"), read as a blank.

#117: a `blank_if` answer is compared without case or marks ("N/A." is "n/a", a dash is
nothing), one that opens with such a word but says more is a reviewer's call, and a person's
corrected value is taken at its word; a rule is turned off only when every slot it reads is
an empty optional one, and the verdict's reasons say so."""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from app.checks.forms import form_of_key
from app.checks.verify import agree, normalise
from app.engine.core import evaluate_item
from app.engine.field_result import FieldResult, overall_status, status_counts, worst_status
from app.engine.normalize import round_to_significant_figures
from app.rulesets.library import load_templates, template_of
from app.rulesets.schema import CheckType, RuleSet, RuleSetItem, Template, TemplateRule

_SLOT_REF = re.compile(r"^\{([a-z][a-z0-9_]*)\}$")
COMPARISONS = {CheckType.VALUE, CheckType.RANGE, CheckType.UNIT, CheckType.DATE, CheckType.MATH,
               CheckType.CROSS_DOCUMENT_MATCH, CheckType.CONTAINS}
INJECTED = {"match": "pass", "mismatch": "needs_review", "unstated": "needs_review"}   # a comparison never disqualifies
_DATE_FORMATS = ("%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%B %d, %Y", "%d %B, %Y", "%d-%m-%Y")


# ---------------------------------------------------------------- values
def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(value or ""))
    return float(m.group(0).replace(",", "")) if m else None


def parse_date(value: Any) -> dt.date | None:
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", str(value or "").strip())
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _equal(value: Any, expected: Any) -> bool:
    """Numbers within half a percent; anything else as two readings agree (V4's rule)."""
    numeric = isinstance(expected, (int, float)) and not isinstance(expected, bool) or re.fullmatch(r"[\d,.\s]+", str(expected))
    a, b = _number(value), _number(expected)
    if numeric and a is not None and b is not None:
        return abs(a - b) <= max(0.005 * abs(b), 1e-9)
    return agree(value, expected)


def _contains(text: Any, phrase: Any) -> bool:
    a, b = normalise(phrase), normalise(text)
    return bool(a) and f" {a} " in f" {b} "


def _decimal_places(text: Any) -> list[int]:
    """The decimal places of every figure written in `text`, as written: "2.50%" has two.
    A comma is a decimal comma only in a figure right before a % ("2,505%" has three); anywhere
    else it groups thousands ("over 12,000" has none). A date ("30.06.2026") is not a figure."""
    text = "" if text is None else str(text)
    out = []
    for m in re.finditer(r"\d+(?:[.,]\d+)*", text):
        token, percent = m.group(0), re.match(r"\s*%", text[m.end():]) is not None
        if token.count(".") > 1 or re.fullmatch(r"\d{1,2}[.,]\d{1,2}[.,]\d{2,4}", token):
            continue
        if "." in token:
            out.append(len(token.rsplit(".", 1)[1]))
        elif token.count(",") == 1 and percent:
            out.append(len(token.split(",")[1]))
        else:
            out.append(0)
    return out


def _flag(value: Any) -> bool:
    """A yes/no param: True, "true", "yes" or 1; "false" is no."""
    return str(value).strip().lower() in ("true", "yes", "1")


def _qualify(name: str, prefix: str) -> str:
    return name if "." in name else f"{prefix}.{name}"


def render_params(rule: TemplateRule, item: RuleSetItem) -> dict:
    """The rule's params with "{slot}" references replaced by the item's slot values."""
    out: dict = {}
    for name, value in rule.params.items():
        if isinstance(value, str) and (m := _SLOT_REF.match(value)):
            slot = item.slots.get(m.group(1))
            out[name] = slot.value if slot is not None else None
        else:
            out[name] = value
    return out


def compare(rule: TemplateRule, params: dict, fields: dict) -> tuple[str, str] | None:
    """The code check behind a comparison kind: ("match" | "mismatch" | "unstated", detail).
    None for a presence kind or a blank field, where the presence outcomes apply."""
    kind = rule.check
    value = fields.get(rule.field)
    if kind == CheckType.HUMAN_ONLY:
        # Nothing submitted, nothing to judge: the presence outcomes apply (#99 review).
        return None if value is None else ("unstated", "a reviewer decides; no automated check")
    if kind not in COMPARISONS:
        return None
    if value is None:
        return None
    # `text` is what the page printed beside a number (a unit, a currency sign), which a
    # person's bare-number correction leaves in place; `shown` is the value as it stands,
    # the person's once corrected (store._apply). Unit and contains checks look in `text`;
    # the messages and the decimal count use `shown`.
    printed = fields.get(f"{rule.field}_printed")
    text = printed if printed is not None else value
    shown = value if fields.get(f"{rule.field}_corrected") else text
    prefix = rule.field.rpartition(".")[0]
    if kind == CheckType.VALUE:
        expected = params.get("expected")
        if expected is None:
            return "unstated", "no expected value to compare with"
        return ("match" if _equal(value, expected) else "mismatch", f"read {shown!r}, expected {expected!r}")
    if kind == CheckType.RANGE:
        lo, hi = _number(params.get("min")), _number(params.get("max"))
        places = _number(params.get("max_decimals"))
        if places is not None:
            # As written, every figure: "2.50%" has two places though it is the number 2.5,
            # and "7-day: 2.505%" is judged by its 2.505. Once a person corrects the value,
            # `shown` is theirs, so their figure is what is counted.
            written = _decimal_places(shown)
            if written and max(written) > places:
                return "mismatch", f"read {shown!r}, {max(written)} decimal places, at most {places:g}"
            if lo is None and hi is None:
                # "Nil" has no figure to count, and is an answer the form allows.
                return "match", (f"read {shown!r}, at most {places:g} decimal places" if written
                                 else f"read {shown!r}, no figure")
        number = _number(value)
        if number is None:
            return "mismatch", f"{shown!r} is not a number"
        if lo is None and hi is None:
            return "unstated", "no bounds to compare with"
        ok = (lo is None or number >= lo) and (hi is None or number <= hi)
        bounds = " to ".join(f"{b:g}" for b in (lo, hi) if b is not None) if lo is not None and hi is not None else \
            (f"at least {lo:g}" if lo is not None else f"at most {hi:g}")
        return ("match" if ok else "mismatch", f"read {shown!r}, allowed {bounds}")
    if kind == CheckType.UNIT:
        allowed = params.get("allowed") or ([params["expected"]] if params.get("expected") else [])
        if not allowed:
            return "unstated", "no unit to compare with"
        ok = any(_contains(text, u) for u in allowed)
        return ("match" if ok else "mismatch", f"read {text!r}, allowed {', '.join(str(u) for u in allowed)}")
    if kind == CheckType.CONTAINS:
        # `phrases`: every one must be there; with `absent`, none may be (an address is not a P.O. Box).
        phrase = params.get("phrase") or params.get("text") or params.get("expected")
        phrases = params.get("phrases") or ([phrase] if phrase else [])
        if isinstance(phrases, str):
            phrases = [phrases]
        phrases = [p for p in phrases if str(p).strip()]
        if not phrases:
            return "unstated", "no phrase to look for"
        found = [p for p in phrases if _contains(text, p)]
        if _flag(params.get("absent")):
            return ("mismatch", f"read {text!r}, which should not contain {found[0]!r}") if found else \
                ("match", f"read {text!r}, none of {', '.join(map(repr, phrases))}")
        missing = [p for p in phrases if p not in found]
        if missing:
            return "mismatch", f"read {text!r}, missing {', '.join(map(repr, missing))}"
        return "match", f"read {text!r}, looked for {', '.join(map(repr, phrases))}"
    if kind == CheckType.DATE:
        date = parse_date(shown)
        if date is None:
            return "mismatch", f"{shown!r} is not a date"
        after, before = parse_date(params.get("after")), parse_date(params.get("before"))
        # A bound given but unreadable ("noon on 30 June") is never skipped: skipped, an
        # expired certificate would pass (#99 review).
        for name, bound, parsed in (("after", params.get("after"), after), ("before", params.get("before"), before)):
            if bound not in (None, "") and parsed is None:
                return "unstated", f"the bound {name} {bound!r} is not a date a person has confirmed"
        if after and date < after:
            return "mismatch", f"{date.isoformat()} is before {after.isoformat()}"
        if before and date > before:
            return "mismatch", f"{date.isoformat()} is after {before.isoformat()}"
        return "match", date.isoformat()
    if kind == CheckType.MATH:
        inputs = [_qualify(str(n), prefix) for n in (params.get("inputs") or [])]
        numbers = [_number(fields.get(n)) for n in inputs]
        reported = _number(value)
        if len(numbers) < 2 or any(n is None for n in numbers) or reported is None:
            return "unstated", "an input is blank or not a number"
        op = str(params.get("op", "product"))
        expected = {"product": numbers[0] * numbers[1], "sum": numbers[0] + numbers[1]}.get(op)
        if expected is None:
            return "unstated", f"unknown operation {op!r}"
        tolerance = _number(params.get("tolerance"))
        tolerance = tolerance if tolerance is not None else max(0.01, 0.005 * abs(expected))
        return ("match" if abs(reported - expected) <= tolerance else "mismatch",
                f"read {reported:g}, the {op} of {' and '.join(inputs)} is {expected:g}")
    if kind == CheckType.CROSS_DOCUMENT_MATCH:
        other = params.get("other") or params.get("field")
        if not other:
            return "unstated", "no other field named"
        other_key = _qualify(str(other), prefix)
        other_value = fields.get(other_key)
        if other_value is None:
            return "unstated", f"{other_key} is blank"
        other_shown = fields.get(f"{other_key}_printed") or other_value
        return ("match" if agree(shown, other_shown) else "mismatch", f"read {shown!r}, {other_key} reads {other_shown!r}")
    return None


# ---------------------------------------------------------------- the engine's vocabulary
def engine_rule(rule: TemplateRule, outcomes: dict | None = None) -> dict:
    out: dict = {
        "id": rule.id,
        "field_id": rule.field,
        "field": rule.field.rsplit(".", 1)[-1].replace("_", " "),
        "check": rule.check.value,
        "consequence_tier": rule.consequence.value if rule.consequence else None,
        "stage": rule.stage,
    }
    if outcomes is not None:
        out["outcomes"] = outcomes
    elif rule.outcomes is not None:
        out["outcomes"] = {k: v.model_dump(exclude_none=True) for k, v in rule.outcomes.items()}
    if rule.depends_on:
        out["depends_on"] = rule.depends_on[0]      # the engine reads one parent until the rule files are split
    if rule.note:
        out["note"] = rule.note
    if rule.condition:
        out["condition"] = rule.condition
    return out


def _tiers(template: Template | None) -> dict:
    tiers: dict = {}
    if template is not None:
        for tier, defaults in template.consequences.items():
            entry: dict = {"outcomes": {k: v.model_dump(exclude_none=True) for k, v in defaults.outcomes.items()}}
            if defaults.follow_up_deadline is not None:
                fd = defaults.follow_up_deadline
                entry["transform"] = {"operation": fd.op, "surfaced_as": "follow_up_deadline",
                                      "params": {"base_date": "follow_up.trigger_date", "offset_value": fd.offset}}
            tiers[tier.value] = entry
    return tiers


def rules_doc(item: RuleSetItem, template: Template | None = None, overrides: dict[str, tuple[str, str]] | None = None) -> dict:
    """The engine's rules document for one item. A rule with a computed comparison gets its
    outcomes (own or tier) plus the injected key the comparison chose."""
    tiers = _tiers(template)
    rules = []
    for rule in item.rules:
        outcomes = None
        if overrides and rule.id in overrides:
            key, detail = overrides[rule.id]
            if rule.outcomes is not None:
                base = {k: v.model_dump(exclude_none=True) for k, v in rule.outcomes.items()}
            else:
                base = dict(tiers.get(rule.consequence.value, {}).get("outcomes", {})) if rule.consequence else {}
            outcomes = {**base, key: {"status": INJECTED[key], "note": f"{{field}}: {detail}"}}
        rules.append(engine_rule(rule, outcomes))
    return {"form_name": item.title, "compliance_schedule_item": f"({item.letter})", "stage": "I",
            "consequence_tiers": tiers, "rules": rules}


def _blank_key(value: Any) -> str:
    """An answer as `blank_if` compares it: lower case, every mark but letters, digits and
    spaces dropped, spaces collapsed. "N/A." and "NA" are one answer, "(Nil)" and "Nil;" are
    "nil", and "-" is nothing at all. Letters of any script count."""
    return " ".join(re.sub(r"[^\w\s]|_", "", str(value).lower()).split())


_RANGE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d[\d,]*(?:\.\d+)?)")


def _step(op: str, params: dict, value: Any) -> float:
    """One normalise step on a value, as a number. Raises ValueError when there is none."""
    if op == "resolve_range_to_lower_bound" and not isinstance(value, (int, float)):
        m = _RANGE.search(str(value))
        if m:
            return min(float(m.group(1).replace(",", "")), float(m.group(2).replace(",", "")))
    number = _number(value)
    if number is None:
        raise ValueError(f"{value!r} is not a number")
    if op == "round_significant_figures":
        return round_to_significant_figures(number, int(params["max_sig_figs"]))
    return number


def normalised(item: RuleSetItem, fields: dict) -> tuple[dict, list[dict], dict[str, tuple[str, str]]]:
    """(the fields with each rule's `normalise` steps applied in order, what changed, and a
    reviewer's note for each rule whose steps could not run). A corrected value arrives as
    text ("4.4 kg/t") and is read as its number first."""
    out, adjustments, failed = dict(fields), [], {}
    for rule in item.rules:
        empty = rule.params.get("blank_if")
        raw = out.get(rule.field)
        if not isinstance(empty, list) or raw is None:
            continue
        said = _blank_key(raw)
        words = {_blank_key(w): str(w) for w in empty if _blank_key(w)}
        if not said or said in words:
            out[rule.field] = None             # "Nil" (or a dash) under non-compliances declares none
        elif fields.get(f"{rule.field}_corrected"):
            continue                           # a person's value is taken at its word
        elif opened := next((w for k, w in words.items() if re.match(rf"{re.escape(k)}(?!\w)", said)), None):
            # "None noted", "Nil (none)", "No deviation from the specification": most likely
            # nothing declared, but not in so many words. A reviewer decides; it is neither a
            # blank (a pass) nor a declaration (which can disqualify) on the wording alone.
            failed[rule.id] = ("unstated", f"{raw!r} opens with {opened!r} but says more; correct it to Nil if "
                                           "nothing is declared, or to what is declared")
    for rule in item.rules:
        value = out.get(rule.field)
        if not rule.normalise or value is None:
            continue
        printed = out.get(f"{rule.field}_printed")
        span = _RANGE.search(printed) if isinstance(printed, str) else None
        # 5.1 read from "5.1 - 4.36 kg/t": the range is in the text. Only a range with the
        # figure read at one end, so "5.1 kg/t (tested 2023-2024)" isn't read as 2023 (#135 review).
        if rule.normalise[0].op == "resolve_range_to_lower_bound" and isinstance(value, (int, float)) and span \
                and not fields.get(f"{rule.field}_corrected") \
                and value in (float(span.group(1).replace(",", "")), float(span.group(2).replace(",", ""))):
            source = printed
        else:
            source = value
        try:
            new = source
            for step in rule.normalise:
                new = _step(step.op, step.params, new)
        except (ValueError, KeyError, ArithmeticError) as exc:
            failed[rule.id] = ("unstated", f"could not normalise: {exc}")
            continue
        if new != value:
            if isinstance(value, str) and out.get(f"{rule.field}_printed") is None:
                # The text stays what a person reads and what a unit check looks in: "4.4 kg/t"
                # is the number 4.4 to the checks that compare, and still in kg/t.
                out[f"{rule.field}_printed"] = value
            out[rule.field] = new
            adjustments.append({"rule_id": rule.id, "field_id": rule.field,
                                "operations": [s.op for s in rule.normalise], "from": value, "value": new})
    return out, adjustments, failed


def prepare(item: RuleSetItem, fields: dict) -> tuple[dict, dict[str, tuple[str, str]], list[dict]]:
    """The fields (normalised) with an explicit outcome for every comparison rule, what was
    decided, and what normalising changed."""
    prepared, adjustments, overrides = normalised(item, fields)
    for rule in item.rules:
        if rule.id in overrides:
            prepared[f"{rule.id}__outcome"] = overrides[rule.id][0]
            continue
        decided = compare(rule, render_params(rule, item), prepared)
        if decided is not None:
            overrides[rule.id] = decided
            prepared[f"{rule.id}__outcome"] = decided[0]
    return prepared, overrides, adjustments


# ---------------------------------------------------------------- code's rules after the engine
def apply_verification(checked: list[FieldResult], fields: dict) -> None:
    """V4's rule, code not engine: a value the verifier could not confirm (`_verification.verified`
    is False) is `needs_review` whatever the engine said, never a pass and never a
    disqualification; the reason is the verifier's note. A field without a verification
    record (an older result, a person's correction) is left to the engine."""
    for f in checked:
        record = fields.get(f"{f.field_id}_verification") or {}
        if record.get("verified") is False and f.status in ("pass", "disqualified"):
            f.status = "needs_review"
            f.note = f"unverified: {record.get('note') or 'the two readings differ'}"


def apply_unextracted(checked: list[FieldResult], fields: dict) -> None:
    """A rule on a field no form reads (no key at all, not even a citation) is a reviewer's
    call: the engine saw a blank, but nothing was looked for."""
    for f in checked:
        if f.field_id not in fields and f"{f.field_id}_page" not in fields:
            f.status = "needs_review"
            f.note = f"unextracted: no form reads {f.field}; a reviewer decides"


def unset_optional_slot_rules(item: RuleSetItem, template: Template | None) -> dict[str, list[str]]:
    """{rule id: its slots} for the rules every slot of which is optional and left empty by the
    tender: the tender sets none of those limits, so the check does not apply (#99 review),
    rather than sending every bid to review for want of a bound. A rule with one of its slots
    set still runs: a range with only its minimum set checks the minimum (#117)."""
    if template is None:
        return {}
    optional = {s.name for s in template.slots if not s.required}
    unset = {name for name in optional if (item.slots.get(name) is None or item.slots[name].value in (None, "", []))}
    return {r.id: sorted(r.slot_refs()) for r in item.rules if r.slot_refs() and r.slot_refs() <= unset}


def without_unset_optional_slots(item: RuleSetItem, template: Template | None) -> RuleSetItem:
    """The item without the rules `unset_optional_slot_rules` names."""
    off = unset_optional_slot_rules(item, template)
    return item if not off else item.model_copy(update={"rules": [r for r in item.rules if r.id not in off]})


def by_reviewer(key: str) -> bool:
    """Whether `key` is a field a person enters after closing, never read off the offer."""
    form = form_of_key(key)
    return form is not None and any(form.key(f.name) == key and f.by == "reviewer" for f in form.all_fields)


REVIEWER_NOTE = "{field} is entered by a reviewer once it arrives; not recorded yet"
DECISIONS = ("pass", "dormant", "disqualified")


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def apply_unread_blanks(checked: list[FieldResult], fields: dict) -> None:
    """A blank the model read on a form that is there never disqualifies on its own: the model
    can miss a signature on a signed page (Tenderer C's offer, 2026-09-30), and a false
    disqualification is the costliest mistake the check can make. The row goes to review; a
    person who marks the field absent, or decides the check, makes it stand. A missing form
    (its `document` blank) still disqualifies at once, unless pages were found for it and only
    the reading says it is not there (`document_located`): a small model can read a form that is
    there as absent, and that goes to review the same way."""
    for f in checked:
        prefix, _, name = f.field_id.rpartition(".")
        if (f.status == "disqualified" and name != "document" and _blank(fields.get(f.field_id))
                and fields.get(f"{prefix}.document") not in (None, False) and not fields.get(f"{f.field_id}_corrected")
                and not fields.get(f"{f.field_id}_redacted")):
            f.status = "needs_review"
            f.note = f"{f.field}: the model read nothing here on a form that is there; a reviewer confirms before it disqualifies"
        elif (f.status == "disqualified" and name == "document" and _blank(fields.get(f.field_id))
                and fields.get(f"{f.field_id}_located") and not fields.get(f"{f.field_id}_corrected")):
            pages = ", ".join(f"p.{s}" for s in fields[f"{f.field_id}_located"])
            f.status = "needs_review"
            f.note = (f"{f.field}: pages were found for this form ({pages}) but the reading says it is not there; "
                      f"a reviewer confirms before it disqualifies")


def apply_decisions(checked: list[FieldResult], fields: dict) -> dict[str, dict]:
    """A reviewer's decision settles a check that needs review: pass, dormant (the Authority
    may ask for it later) or disqualified, with who and why. A decision on a check that no
    longer needs review (the value was corrected since, the rule set changed) is set aside.
    Returns {field_id: decision} for the checks it settled."""
    settled = {}
    for f in checked:
        decision = fields.get(f"{f.field_id}_decision")
        if f.status == "needs_review" and isinstance(decision, dict) and decision.get("status") in DECISIONS:
            f.status, f.follow_up = decision["status"], None
            f.note = f"decided by {decision.get('by') or 'a reviewer'}: {decision.get('reason') or 'no reason given'}"
            settled[f.field_id] = decision
    return settled


def apply_reviewer_fields(item: RuleSetItem, checked: list[FieldResult], fields: dict) -> None:
    """A blank field a reviewer enters is dormant, whatever the rule's outcomes say: nobody
    could have entered it yet, so it never disqualifies (an L3 rule with Part A outcomes
    would). A rule the engine made no row for (no blank outcome) gets one, so there is
    somewhere to enter the value; unless the rule it depends on blocked it."""
    rows = {f.field_id: f for f in checked}
    for f in checked:
        if by_reviewer(f.field_id) and fields.get(f.field_id) is None:
            f.status, f.note, f.follow_up = "dormant", REVIEWER_NOTE.format(field=f.field), None
    by_id = {r.id: r for r in item.rules}
    for rule in item.rules:
        if rule.field in rows or not by_reviewer(rule.field) or fields.get(rule.field) is not None:
            continue
        parent = by_id.get(rule.depends_on[0]) if rule.depends_on else None
        if parent is not None and (rows.get(parent.field) is None or rows[parent.field].status in ("dormant", "disqualified")):
            continue
        name = rule.field.rsplit(".", 1)[-1].replace("_", " ")
        rows[rule.field] = FieldResult(field_id=rule.field, field=name, value=None, status="dormant", confidence=None,
                                       source=None, note=REVIEWER_NOTE.format(field=name), stage=rule.stage)
        checked.append(rows[rule.field])


def evaluate(item: RuleSetItem, fields: dict, template: Template | None = None) -> dict:
    """The verdict for one item: the engine's overall status (dormant fields do not count
    against a tender as submitted today; an item whose every field is dormant is dormant),
    the worst status including dormant, every checked field with its status, stage and
    note, and the reasons a reviewer reads."""
    blocked = None
    tierless = [r for r in item.rules if r.consequence is not None and r.outcomes is None
                and template is not None and r.consequence not in template.consequences]
    if not item.rules:
        blocked = f"item ({item.letter}) has no rules; a reviewer decides"
    elif item.template and template is None and any(r.consequence is not None and r.outcomes is None for r in item.rules):
        blocked = f"item ({item.letter}): template {item.template!r} is not in the library, so its rules have no outcomes; a reviewer decides"
    elif tierless:
        blocked = (f"item ({item.letter}): rule {tierless[0].id} names tier {tierless[0].consequence.value!r}, which template "
                   f"{template.id!r} does not define, so it would never be checked; a reviewer decides")
    if blocked:
        return {"item": item.letter, "part": item.part.value, "outcome": "needs_review", "worst": "needs_review",
                "counts": status_counts([]), "rule_ids": [r.id for r in item.rules], "fields": [], "reasons": [blocked]}
    off = unset_optional_slot_rules(item, template)
    item = without_unset_optional_slots(item, template)
    prepared, overrides, adjustments = prepare(item, fields)
    result = evaluate_item([rules_doc(item, template, overrides)], prepared, item.letter)
    for f in result.fields:
        if (f.note or "").startswith("Could not be automatically determined"):
            # The engine's own wording names its internal key ("…__outcome"); a reviewer reads this.
            f.note = f"{f.field} reads {f.value!r}, an answer this rule has no outcome for; a reviewer decides"
    apply_verification(result.fields, fields)
    apply_unextracted(result.fields, fields)
    apply_reviewer_fields(item, result.fields, fields)
    apply_unread_blanks(result.fields, fields)
    decided = apply_decisions(result.fields, fields)
    checked = [{"field_id": f.field_id, "field": f.field, "status": f.status, "note": f.note, "value": f.value,
                "redacted": f.redacted, "stage": f.stage,
                "follow_up": None if f.follow_up is None else vars(f.follow_up),
                "page": fields.get(f"{f.field_id}_page"),
                # Only when there is one: a stored verdict without the key must compare equal.
                **({"decision": decided[f.field_id]} if f.field_id in decided else {})} for f in result.fields]
    outcome = overall_status(result.fields)
    if result.fields and all(f.status == "dormant" for f in result.fields):
        outcome = "dormant"
    verdict = {
        "item": item.letter,
        "part": item.part.value,
        "outcome": outcome,
        "worst": worst_status([f["status"] for f in checked]),
        "counts": status_counts(result.fields),
        "rule_ids": [r.id for r in item.rules],
        "fields": checked,
        "reasons": [f["note"] for f in checked if f["status"] != "pass" and f["note"]]
                   + [f"rule {rule_id} not checked: the tender sets no {', '.join(slots)}" for rule_id, slots in off.items()],
    }
    if adjustments:
        # Only when something changed: a stored verdict without the key must still compare
        # equal (store._same_verdict), or every confirmed review would be withdrawn.
        verdict["adjustments"] = adjustments
    return verdict


def stage_summary(items: dict[str, dict], stage: str) -> dict:
    """{outcome, items: {letter: outcome}} over the fields checked at one stage; an item with
    nothing at that stage is left out; dormant counts only when nothing else is there."""
    per: dict[str, str] = {}
    for letter, v in items.items():
        statuses = [f["status"] for f in v.get("fields", []) if f.get("stage", "I") == stage]
        if not statuses and v.get("outcome") == "needs_review" and not v.get("fields") and stage == "I":
            statuses = ["needs_review"]                                    # an item with no rules
        if not statuses:
            continue
        live = [s for s in statuses if s != "dormant"]
        per[letter] = worst_status(live) if live else "dormant"
    live = [s for s in per.values() if s != "dormant"]
    return {"outcome": worst_status(live) if live else ("dormant" if per else "pass"), "items": per}


def decide(fields: dict, spec: dict) -> dict:
    """The pipeline's engine-only decision on every item of a confirmed RuleSet as stored:
    {ruleset_version, outcome (Stage I), items: {letter: verdict}, stage1, stage2 | null}."""
    ruleset = RuleSet.model_validate(spec)
    templates = load_templates()
    items = {}
    for item in ruleset.items:
        items[item.letter] = evaluate(item, fields, template_of(item, templates))
    stage1, stage2 = stage_summary(items, "I"), stage_summary(items, "II")
    return {"ruleset_version": ruleset.version, "outcome": stage1["outcome"], "items": items,
            "stage1": stage1, "stage2": stage2 if stage2["items"] else None}


def decide_item_l(fields: dict, spec: dict) -> dict:
    """Item (l)'s verdict alone, as the S2 tests read it."""
    verdict = decide(fields, spec)
    return {**verdict["items"]["l"], "ruleset_version": verdict["ruleset_version"]}

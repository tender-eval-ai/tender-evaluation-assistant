"""The confirmed rule set for every item of the synthetic tender case, written to
test/data/synthetic_tender/ruleset_all_items.json: what a person would have confirmed after L1
to L4 on that tender. Items (b) and (l) carry the two test templates' rules (their tiers
come from test/data/templates at decide time); the rest are novel rules with their own
outcomes by Part, on the fields of app/checks/forms.py. Regenerate with:

    python tools/make_synthetic_tender_ruleset.py"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.checks.forms import FORMS  # noqa: E402
from app.rulesets.library import load_templates  # noqa: E402
from app.rulesets.novel import outcomes_for  # noqa: E402
from app.rulesets.schema import (Citation, Edit, ItemNote, ItemStatus, Outcome, Part, RuleSet, RuleSetItem, SlotValue,  # noqa: E402
                                 TemplateRule)

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "test" / "data" / "synthetic_tender"
TEMPLATES = ROOT / "test" / "data" / "templates"
OUT = CASE / "ruleset_all_items.json"
WHEN = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)

PARTS = {"a": "A", "b": "A", "c": "A", "d": "A", "e": "B", "f": "B", "g": "B", "h": "B", "i": "A", "j": "B", "k": "B",
         "l": "A", "m": "C", "n": "A", "o": "B"}
TITLES = {
    "a": "The Offer to be Bound in Part 4 of the Tender Form, duly signed",
    "b": "The one-time unit price quotation for Item 1 in Part A of the Price Schedule",
    "c": "The optimal dosage for Item 1 in Part A of the Price Schedule",
    "d": "The essential information required in the Particulars of Goods Schedule",
    "e": "Other information required in the Particulars of Goods Schedule",
    "f": "Information and documents required in Tables A, B and C of the Information Schedule",
    "g": "Samples of the Goods, if requested by the Authority",
    "h": "Documentary evidence proving compliance with the Technical Specifications",
    "i": "Where the Tenderer is not the manufacturer of the Goods, the letter of intent from the manufacturer",
    "j": "A certified extract of the board resolution authorising the signatory of the Tender",
    "k": "The contact details in the Appendix to the Terms of Tender",
    "l": "The signed Non-collusive Tendering Certificate",
    "m": "Parts C and D of the Price Schedule",
    "n": "The Compliance Schedule",
    "o": "The Method of Production Statement in Annex A Part I",
}


def novel(form_id: str, name: str, check: str, field: str, part: str, *, params: dict | None = None, stage: str = "I",
          depends_on: list[str] | None = None, outcomes: dict | None = None, condition: str | None = None) -> TemplateRule:
    form = FORMS[form_id]
    return TemplateRule(id=f"{form_id}.{name}", check=check, field=form.key(field), params=params or {}, stage=stage,
                        depends_on=depends_on or [], condition=condition,
                        outcomes=outcomes or outcomes_for(Part(part)))


def submitted(form_id: str, part: str, **kw) -> TemplateRule:
    return novel(form_id, "submitted", "document_present", "document", part, **kw)


def build() -> RuleSet:
    truth = json.loads((CASE / "ground_truth.json").read_text())
    rows = {r["letter"]: r for r in truth["tender"]["completeness_check_schedule"]["items"]}
    templates = load_templates(TEMPLATES)
    price, cert = templates["price_schedule"], templates["noncollusive_certificate"]
    quantity = truth["estimated_quantity_kg"]
    rules: dict[str, list[TemplateRule]] = {
        "a": [submitted("offer_to_be_bound", "A"),
              novel("offer_to_be_bound", "signed", "signature", "signature", "A", depends_on=["offer_to_be_bound.submitted"]),
              novel("offer_to_be_bound", "dated", "date", "date", "A", depends_on=["offer_to_be_bound.signed"])],
        "b": [r.model_copy(deep=True) for r in price.rules] + [
              TemplateRule(id="price_schedule.currency_permitted", check="unit", field="price_schedule.unit_price",
                           params={"allowed": ["HK$", "US$"]}, consequence="critical", depends_on=["price_schedule.unit_price_present"]),
              TemplateRule(id="price_schedule.total_is_unit_price_times_quantity", check="math", field="price_schedule.total",
                           params={"inputs": ["unit_price", "quantity"], "op": "product"}, consequence="critical",
                           depends_on=["price_schedule.unit_price_present"])],
        "c": [novel("price_schedule", "dosage_present", "filled", "optimal_dosage", "A"),
              novel("price_schedule", "dosage_unit", "unit", "optimal_dosage", "A", params={"allowed": ["mg/L"]},
                    depends_on=["price_schedule.dosage_present"]),
              novel("price_schedule", "dosage_plausible", "range", "optimal_dosage", "A", params={"min": 0.5, "max": 20},
                    stage="II", depends_on=["price_schedule.dosage_present"])],
        "d": [submitted("particulars_of_goods", "A"),
              novel("particulars_of_goods", "manufacturer_named", "filled", "manufacturer", "A", depends_on=["particulars_of_goods.submitted"]),
              novel("particulars_of_goods", "shelf_life_stated", "filled", "shelf_life_months", "A", depends_on=["particulars_of_goods.submitted"]),
              novel("particulars_of_goods", "shelf_life_at_least_twelve_months", "range", "shelf_life_months", "A",
                    params={"min": 12}, stage="II", depends_on=["particulars_of_goods.shelf_life_stated"])],
        "e": [novel("particulars_of_goods", "country_stated", "filled", "country_of_origin", "B")],
        "f": [submitted("information_schedule", "B"),
              novel("information_schedule", "track_record_given", "filled", "track_record", "B", depends_on=["information_schedule.submitted"])],
        "g": [submitted("tender_sample_declaration", "B")],
        "h": [submitted("documentary_evidence", "B")],
        "i": [submitted("manufacturer_letter", "A", condition="the Tenderer is not the manufacturer of the Goods", outcomes={
              "blank": Outcome(status="needs_review", note="{field} is missing; required only where the tenderer is not the "
                                                           "manufacturer, so a reviewer decides"),
              "filled": Outcome(status="pass"),
              "not_applicable": Outcome(status="pass", note="{field} not required: the tenderer is the manufacturer"),
              "redacted": Outcome(status="needs_review", note="{field} is covered; ask for an unredacted copy")})],
        "j": [submitted("board_resolution", "B")],
        "k": [submitted("contact_details", "B"),
              novel("contact_details", "contact_person_given", "filled", "contact_person", "B", depends_on=["contact_details.submitted"]),
              novel("contact_details", "email_given", "filled", "email", "B", depends_on=["contact_details.submitted"])],
        "l": [r.model_copy(deep=True) for r in cert.rules],
        "m": [submitted("price_schedule_parts_c_d", "C")],
        "n": [submitted("compliance_schedule", "A"),
              novel("compliance_schedule", "delivery_stated", "filled", "delivery_days", "A", depends_on=["compliance_schedule.submitted"]),
              novel("compliance_schedule", "delivery_within_thirty_days", "range", "delivery_days", "A", params={"max": 30},
                    stage="II", depends_on=["compliance_schedule.delivery_stated"])],
        "o": [submitted("method_of_production", "B")],
    }
    items = []
    for letter, part in PARTS.items():
        row = rows[letter]
        template = {"b": "price_schedule", "l": "noncollusive_certificate"}.get(letter)
        slots = {}
        if template == "price_schedule":
            slots = {"estimated_quantity": SlotValue(value=quantity, origin="extracted", verified=True,
                                                     citation=Citation(file="tender/09 Schedules.pdf", page=1,
                                                                       quote=f"is {quantity:,} kg", data_class="synthetic")),
                     # The synthetic tender lets a price be quoted in HK$ or US$ but states no rate, as a
                     # real one may leave it to the panel: both are set by hand, with the reason.
                     "currency": SlotValue(value="HK$", origin="manual", edit=Edit(
                         by="chenyu", at=WHEN, reason="set by the evaluation panel: every price is compared in HK$")),
                     "exchange_rates": SlotValue(value={"USD": 7.8}, origin="manual", edit=Edit(
                         by="chenyu", at=WHEN, reason="set by the evaluation panel: the rate a US$ quotation is converted at"))}
        items.append(RuleSetItem(
            letter=letter, title=TITLES[letter], part=Part(part), template=template,
            citation=Citation(file="tender/09 Schedules.pdf", page=row["schedule_page"], node_id=f"Sched:CCS:({letter})",
                              quote=f"({letter}) {row['description']}", data_class="synthetic"),
            clauses=[Citation(file=ref["file"], page=ref["page"], quote=f"Paragraph {ref['paragraph']}", data_class="synthetic")
                     for ref in row["references"]],
            notes=[ItemNote(kind="reference", text=f"Part {part}: " + {
                "A": "a missing item means the tender is not considered further",
                "B": "a missing item may be requested by the Authority before it decides",
                "C": "a discretionary item; the Authority may ask for it later"}[part])],
            slots=slots, rules=rules[letter],
            status=ItemStatus.VERIFIED if template else ItemStatus.NOVEL))
    return RuleSet(project_id="SYN-2026-001", version=1, status="confirmed", data_class="synthetic", items=items,
                   created_by="chenyu", created_at=WHEN, confirmed_by="nasi", confirmed_at=WHEN)


def main() -> None:
    ruleset = build()
    OUT.write_text(json.dumps(ruleset.model_dump(mode="json"), indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(ruleset.items)} items, {sum(len(i.rules) for i in ruleset.items)} rules")


if __name__ == "__main__":
    main()

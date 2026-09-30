"""The closed menu of forms an offer is made of, one per page label that serves a
Completeness Check Schedule item, each with its fixed field menu.

A form's id is the prefix of its flat keys (`price_schedule.unit_price`); the same names
are what a template's rules and a drafted rule refer to, so extraction (V3), verification
(V4), the rule builder (L1 to L3) and the engine bridge (V6) all speak one vocabulary.
A field is read as printed; `number` fields are also coerced (the printed form is kept
beside them as `_printed`), a `signature` field holds the printed name or title next to
the signature, "signature present" when only a signature or chop is visible, and null
when unsigned. Every form has `document`: its heading as printed, null when absent."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.checks.labels import PAGE_LABELS, labels_for
from app.checks.verify import FieldSpec

Kind = Literal["text", "number", "date", "signature"]


@dataclass(frozen=True)
class FieldDef:
    name: str
    kind: Kind
    hint: str
    # "reviewer": not on any page of the offer (a tender sample's weight, the date a test
    # report arrived on request). V3 never asks for it and V4 never checks it; it stays
    # blank until a person enters it as a correction, so its rule waits, dormant, till then.
    by: Literal["reading", "reviewer"] = "reading"


@dataclass(frozen=True)
class Form:
    id: str                       # the key prefix
    label: str                    # the page label V1 gives its pages
    title: str
    fields: tuple[FieldDef, ...]  # after the implicit `document`
    phrases: tuple[str, ...] = ()  # how a schedule row names this form (see form_for_title)

    @property
    def letters(self) -> tuple[str, ...]:
        """The schedule items this form serves in the synthetic case's (and Tender 1's)
        lettering. Only the legacy per-letter resolve uses it; `form_for` goes by title."""
        return PAGE_LABELS[self.label]

    @property
    def all_fields(self) -> tuple[FieldDef, ...]:
        return (DOCUMENT,) + self.fields

    @property
    def read_fields(self) -> tuple[FieldDef, ...]:
        """The fields V3 reads off the offer's pages: all but those a reviewer enters."""
        return tuple(f for f in self.all_fields if f.by == "reading")

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.all_fields)

    def key(self, name: str) -> str:
        return f"{self.id}.{name}"

    def specs(self) -> tuple[FieldSpec, ...]:
        """What V4 checks: every field read off the pages; a signature agrees on presence, not wording."""
        return tuple(FieldSpec(self.key(f.name), f.hint, presence=f.kind == "signature") for f in self.read_fields)


DOCUMENT = FieldDef("document", "text", "the form's heading as printed")
SIGNATURE_HINT = ("the printed name or title next to the signature; 'signature present' when only a signature "
                  "or chop is visible; null when it is not signed")


def reviewer(name: str, kind: Kind, hint: str) -> FieldDef:
    """A field a person enters after the tender closes; never read off the offer."""
    return FieldDef(name, kind, hint, by="reviewer")

_FORMS = (
    Form("offer_to_be_bound", "tender_form_offer_to_be_bound", "Tender Form, Offer to be Bound", (
        FieldDef("tenderer_name", "text", "the tenderer's name as written in the offer"),
        FieldDef("signature", "signature", SIGNATURE_HINT),
        FieldDef("date", "date", "the date as printed next to the signature"),
        FieldDef("chop", "text", "what says a company chop or seal is affixed, as printed; null when none"),
    ), phrases=("Offer to be Bound",)),
    Form("price_schedule", "price_schedule_part_a", "Price Schedule, Part A", (
        FieldDef("unit_price", "number", "the unit price quoted, with its currency and unit as printed"),
        FieldDef("currency", "text", "the currency the unit price is quoted in, as printed (e.g. HK$, US$)"),
        FieldDef("optimal_dosage", "number", "the optimal dosage quoted, with its unit as printed"),
        FieldDef("quantity", "number", "the estimated quantity printed on the schedule, with its unit"),
        FieldDef("total", "number", "the total quoted, with its currency as printed"),
        FieldDef("signature", "signature", SIGNATURE_HINT),
    ), phrases=("Price Schedule",)),
    Form("price_schedule_parts_c_d", "price_schedule_parts_c_d", "Price Schedule, Parts C and D", (
        FieldDef("discount_7day", "text", "Part C (a): the discount for payment within 7 working days, as printed "
                                          "(a percentage, or 'Nil'); null when blank"),
        FieldDef("discount_8to14day", "text", "Part C (b): the discount for payment within 8 to 14 working days, as "
                                              "printed (a percentage, or 'Nil'); null when blank"),
        FieldDef("part_d", "text", "what is entered under Part D (the bank account details), as printed"),
    ), phrases=("Parts C and D of the Price Schedule",)),
    Form("particulars_of_goods", "particulars_of_goods_schedule", "Particulars of Goods Schedule", (
        FieldDef("product_name", "text", "the product name and grade as printed"),
        FieldDef("manufacturer", "text", "the manufacturer's name (and address) as printed"),
        FieldDef("country_of_origin", "text", "the country of origin as printed"),
        FieldDef("shelf_life_months", "number", "the shelf life as printed, with its unit"),
        FieldDef("packaging", "text", "the packaging and container size as printed"),
        FieldDef("net_weight_kg", "number", "the net weight of one package, as printed, with its unit"),
        FieldDef("active_ingredient_pct", "number", "the active ingredient content as printed"),
        FieldDef("bulk_density", "number", "the bulk density as printed, with its unit"),
        FieldDef("manufacturing_plant_address", "text", "the address of the plant where the goods are made, as printed"),
        FieldDef("product_code", "text", "the manufacturer's product code or number, as printed"),
        # The rows that describe the product differ from tender to tender (#76 review, point 3), so
        # rather than one field per row, one field says which rows the tenderer left empty. A
        # stop-gap (#100 review): a row the model misses reads as "none empty" and cannot be
        # verified, so a template treats a blank here as a reviewer's call. The lasting answer
        # is V3 reading the schedule as {row label: value}, checked against a per-tender list.
        FieldDef("rows_left_blank", "text", "the names of the schedule's rows left empty, as printed, separated by "
                                            "semicolons; a row marked 'N/A' is not empty; null when every row is "
                                            "filled in"),
    ), phrases=("Particulars of Goods",)),
    Form("information_schedule", "information_schedule", "Information Schedule", (
        FieldDef("track_record", "text", "the track record of supply the schedule lists, as printed"),
        FieldDef("quality_certification", "text", "the quality certification the schedule states, as printed"),
        FieldDef("production_capacity", "text", "the production capacity the schedule states, as printed"),
        # Table B, the tenderer's particulars: each as entered, or what is marked as attached
        FieldDef("tenderer_name", "text", "Table B: the tenderer's name as entered"),
        FieldDef("telephone", "text", "Table B: the tenderer's telephone number as entered"),
        FieldDef("facsimile", "text", "Table B: the tenderer's fax number as entered"),
        FieldDef("email", "text", "Table B: the tenderer's e-mail address as entered"),
        FieldDef("principal_place_of_business", "text", "Table B: the principal place of business as entered"),
        FieldDef("business_entity_type", "text", "Table B: the type of business entity ticked or entered"),
        FieldDef("shareholders_ownership", "text", "Table B: the shareholders or owners and their shares, as entered"),
        FieldDef("business_experience_length", "text", "Table B: how long the tenderer has been in the business, as entered"),
        FieldDef("directors_partners_names", "text", "Table B: the names of the directors or partners, as entered"),
        FieldDef("incorporation_place_date", "text", "Table B: the place and date of incorporation or registration, as entered"),
        FieldDef("business_profile_info", "text", "Table B: the business profile given, as entered"),
        FieldDef("business_registration_certificate", "text", "Table B: the Business Registration Certificate, what is "
                                                              "entered or marked as attached; null when neither"),
        FieldDef("certificate_of_incorporation", "text", "Table B: the Certificate of Incorporation, what is entered or "
                                                         "marked as attached; null when neither"),
        FieldDef("certificate_of_change_of_name", "text", "Table B: any Certificate of Change of Name, what is entered or "
                                                          "marked as attached; null when neither"),
        FieldDef("memorandum_articles_of_association", "text", "Table B: the Memorandum and Articles of Association, what "
                                                               "is entered or marked as attached; null when neither"),
        FieldDef("latest_annual_return", "text", "Table B: the latest annual return, what is entered or marked as attached; "
                                                 "null when neither"),
        FieldDef("employees_compensation_insurance", "text", "Table B: the employees' compensation insurance, what is "
                                                             "entered or marked as attached; null when neither"),
        # Table C, subcontracting: 'Not applicable' is an answer, blank is not
        FieldDef("subcontractor_name", "text", "Table C: the subcontractor's name as entered, or 'Not applicable'"),
        FieldDef("subcontractor_place_of_business", "text", "Table C: the subcontractor's place of business as entered"),
        FieldDef("subcontractor_obligations", "text", "Table C: what the subcontractor will do, as entered"),
        FieldDef("subcontractor_undertaking", "text", "Table C: the subcontractor's undertaking, what is entered or marked "
                                                      "as attached"),
        FieldDef("subcontractor_overseas_legal_opinion", "text", "Table C: the legal opinion for an overseas subcontractor, "
                                                                 "what is entered or marked as attached"),
        FieldDef("subcontractor_service_centre_location", "text", "Table C: the location of the service centre, as entered"),
        # Table D, the disclosure of events
        FieldDef("event_disclosure_box", "text", "Table D: which box is ticked and any events disclosed, as printed; null "
                                                 "when no box is ticked"),
    ), phrases=("Information Schedule",)),
    Form("tender_sample_declaration", "tender_sample_declaration", "Tender Sample Declaration", (
        FieldDef("declaration", "text", "the declaration as printed"),
        # A sample is delivered when the Authority asks, after the tender closes: a reviewer records it.
        reviewer("sample_received_date", "date", "the date the tender sample was delivered, from the Authority's receipt"),
        reviewer("sample_net_weight_kg", "number", "the total net weight of the tender sample delivered, in kg"),
        reviewer("sample_pack_net_weight_kg", "number", "the net weight of one pack of the sample, in kg"),
        reviewer("sample_label", "text", "the particulars on the sample's label, as written"),
        reviewer("sample_condition", "text", "how the sample arrived: its packing and seal, as the reviewer found them"),
        reviewer("sample_charges", "text", "any charge the tenderer asks for the sample; null when none"),
        reviewer("additional_sample_received_date", "date", "the date an additional quantity asked for during a "
                                                            "plant trial was delivered"),
        reviewer("plant_trial_result", "text", "the outcome of the plant trial, as the Authority recorded it"),
    ), phrases=("tender sample", "samples of the goods")),
    Form("documentary_evidence", "documentary_evidence_of_compliance", "Documentary Evidence of Compliance", (
        FieldDef("evidence", "text", "the evidence listed or attached, as printed (report numbers, certificates)"),
        # One home for each document (#76 review, point 2): the documents a tender asks for as evidence
        # are read here, not from the Information Schedule rows that point to them.
        FieldDef("quality_certificate", "text", "the quality management system certificate attached: its number and "
                                                "the body that issued it, as printed; null when none"),
        FieldDef("quality_certificate_scope", "text", "the scope of certification the quality certificate states, "
                                                      "as printed"),
        FieldDef("quality_certificate_site", "text", "the site address the quality certificate covers, as printed"),
        FieldDef("quality_certificate_expiry", "date", "the date the quality certificate expires, as printed"),
        FieldDef("accreditation_schedule", "text", "the schedule of accreditation attached with the quality "
                                                   "certificate: its title as printed; null when none"),
        FieldDef("safety_data_sheet", "text", "the safety data sheet attached: the product it covers and who issued "
                                              "it, as printed; null when none"),
        FieldDef("safety_data_sheet_sections", "text", "the section headings of the safety data sheet that have text "
                                                       "beneath them, as printed, separated by semicolons"),
        FieldDef("product_specifications", "text", "the product specifications attached: their title and who issued "
                                                   "them, as printed; null when none"),
        FieldDef("product_specifications_date", "date", "the issue date of the product specifications, as printed"),
        FieldDef("evaluation_report", "text", "the tenderer's own evaluation report attached: its title, as printed; "
                                              "null when none"),
        FieldDef("evaluation_report_contents", "text", "the headings or parts the evaluation report contains, as "
                                                       "printed, separated by semicolons"),
        # A conformance test happens only when the Authority asks for one: a reviewer records it.
        reviewer("laboratory_appointed_date", "date", "the date the tenderer appointed a laboratory for a "
                                                      "conformance test the Authority asked for"),
        reviewer("test_report_received_date", "date", "the date the laboratory's test report was received"),
        reviewer("test_report", "text", "the test report received: its number and the laboratory, as written"),
        reviewer("laboratory_independence_declaration", "text", "the tenderer's declaration that the laboratory is "
                                                                "independent of it and of the manufacturer, as received"),
    ), phrases=("documentary evidence",)),
    Form("manufacturer_letter", "manufacturer_letter_of_intent", "Manufacturer's Letter of Intent", (
        FieldDef("manufacturer", "text", "the manufacturer's name as printed"),
        FieldDef("tenderer_name", "text", "the tenderer the letter names, as printed"),
        FieldDef("signature", "signature", SIGNATURE_HINT),
    ), phrases=("letter of intent",)),
    Form("board_resolution", "board_resolution", "Certified Extract of Board Resolution", (
        FieldDef("resolution", "text", "what is resolved, as printed"),
        FieldDef("certified_by", "text", "who certifies the extract, as printed"),
    ), phrases=("board resolution",)),
    Form("contact_details", "contact_details", "Appendix to the Terms of Tender, Contact Details", (
        FieldDef("tenderer_name", "text", "the name of the tenderer as printed"),
        FieldDef("contact_person", "text", "the contact person as printed"),
        FieldDef("telephone", "text", "the telephone number as printed"),
        FieldDef("email", "text", "the e-mail address as printed"),
        FieldDef("address", "text", "the correspondence address as printed"),
        FieldDef("facsimile", "text", "the fax number as printed"),
        FieldDef("process_agent", "text", "the process agent's name and address, as printed; null when that part is "
                                          "not completed"),
    ), phrases=("contact details",)),
    Form("noncollusive_certificate", "noncollusive_certificate", "Non-collusive Tendering Certificate", (
        FieldDef("tenderer_name", "text", "the tenderer's name as written on the certificate"),
        FieldDef("signature", "signature", SIGNATURE_HINT),
        FieldDef("date", "date", "the date as printed next to the signature"),
    ), phrases=("Non-collusive Tendering Certificate",)),
    Form("compliance_schedule", "compliance_schedule", "Compliance Schedule", (
        FieldDef("delivery_days", "number", "the delivery period the tenderer states, as printed, with its unit"),
        FieldDef("non_compliances", "text", "the rows marked 'Not comply', as printed; null when every row complies"),
        # Each Part's mark only: what a Part covers differs by tender (delivery, shelf life, production
        # capacity, ...), so the rule set says what it means and the value a Part asks for is its own field.
        FieldDef("part_a", "text", "Part A: the mark or entry against it, as printed (a tick, 'comply', 'not comply'); "
                                   "null when blank"),
        FieldDef("part_b", "text", "Part B: the mark or entry against it, as printed; null when blank"),
        FieldDef("part_c", "text", "Part C: the mark or entry against it, as printed; null when blank"),
        FieldDef("part_d", "text", "Part D: the mark or entry against it, as printed; null when blank"),
        FieldDef("part_e", "text", "Part E, where the schedule has one: the mark or entry against it, as printed; null "
                                   "when blank or absent"),
        FieldDef("shelf_life_months", "number", "the shelf life the tenderer proposes, as printed with its unit, where "
                                                "the schedule lets it propose a longer one; null when none"),
    ), phrases=("Compliance Schedule",)),
    Form("method_of_production", "method_of_production_statement", "Method of Production Statement", (
        FieldDef("statement", "text", "the statement as printed, its first sentence"),
    ), phrases=("Method of Production",)),
    Form("contract_deposit", "contract_deposit_annex", "Annex A to the Terms of Tender, Method of providing the Contract Deposit", (
        FieldDef("method", "text", "the method left standing after the deletions, as printed: in cash, or by way of a banker's guarantee"),
        FieldDef("refund_method", "text", "Part IB where the form has one: the ticked way of receiving the refund, as printed; null when not ticked"),
    ), phrases=("Contract Deposit",)),
)

FORMS: dict[str, Form] = {f.id: f for f in _FORMS}
FORM_OF_LABEL: dict[str, Form] = {f.label: f for f in _FORMS}


def forms_for_letter(letter: str) -> list[Form]:
    """The forms that serve a schedule item, by the label vocabulary."""
    return [FORM_OF_LABEL[label] for label in labels_for(letter) if label in FORM_OF_LABEL]


def _squash(text: str) -> str:
    """Lower-case letters and digits only: the parser splits words ("I nformation") and
    quotes phrases ("“ Offer to be Bound ”"), neither of which should decide a match."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def form_for_title(text: str) -> Form | None:
    """The form a Completeness Check Schedule row names. The phrase found earliest in the row
    wins, the longer one on a tie: a row for the board resolution goes on to mention
    "documentary evidence" and the Offer to be Bound, and "Parts C and D of the Price
    Schedule" contains "Price Schedule". None when the row names no form of the menu."""
    squashed = _squash(text)
    best: tuple[int, int, Form] | None = None
    for form in _FORMS:
        for phrase in form.phrases:
            at = squashed.find(_squash(phrase))
            if at >= 0 and (best is None or (at, -len(_squash(phrase))) < best[:2]):
                best = (at, -len(_squash(phrase)), form)
    return best[2] if best else None


def form_for(item) -> Form | None:
    """The form a rule-set item's fields come from: the template's form when its id is one,
    else the form its schedule row names, from the item's title and then its full quote
    (the title is cut at the first sentence). None for a row that names no form: that item
    goes to a reviewer. Never by letter: the letters in `labels.py` are Tender 1's and the
    synthetic case's, and another tender puts other items under the same letters."""
    template = getattr(item, "template", None)
    if template and template in FORMS:
        return FORMS[template]
    citation = getattr(item, "citation", None)
    return form_for_title(getattr(item, "title", "") or "") or form_for_title(getattr(citation, "quote", "") or "")


def form_of_key(key: str) -> Form | None:
    prefix = key.rpartition(".")[0]
    return FORMS.get(prefix)

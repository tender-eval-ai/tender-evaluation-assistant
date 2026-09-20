"""V1's closed vocabulary. A page of an offer is one of these; the labels that serve a
Completeness Check Schedule item are named after it, so V2 can find an item's pages
from the labels alone."""
from __future__ import annotations

PAGE_LABELS: dict[str, tuple[str, ...]] = {
    "cover_or_contents": (),
    "company_profile": (),
    "other": (),
    "tender_form_offer_to_be_bound": ("a",),
    "price_schedule_part_a": ("b", "c"),
    "price_schedule_parts_c_d": ("m",),
    "particulars_of_goods_schedule": ("d", "e"),
    "information_schedule": ("f",),
    "tender_sample_declaration": ("g",),
    "documentary_evidence_of_compliance": ("h",),
    "manufacturer_letter_of_intent": ("i",),
    "board_resolution": ("j",),
    "contact_details": ("k",),
    "noncollusive_certificate": ("l",),
    "compliance_schedule": ("n",),
    "method_of_production_statement": ("o",),
}

ITEM_TITLES = {
    "a": "the Offer to be Bound in the Tender Form", "b": "the unit price in Part A of the Price Schedule",
    "c": "the optimal dosage in Part A of the Price Schedule", "d": "the Particulars of Goods Schedule",
    "e": "the Particulars of Goods Schedule", "f": "the Information Schedule", "g": "the tender sample declaration",
    "h": "the documentary evidence of compliance", "i": "the manufacturer's letter of intent",
    "j": "the certified extract of the board resolution", "k": "the contact details appendix",
    "l": "the signed Non-collusive Tendering Certificate", "m": "Parts C and D of the Price Schedule",
    "n": "the Compliance Schedule", "o": "the Method of Production Statement",
}


def labels_for(letter: str) -> list[str]:
    return [label for label, letters in PAGE_LABELS.items() if letter in letters]


def normalise(label: str) -> str:
    """A label outside the vocabulary becomes 'other'; the model never invents a kind."""
    return label if label in PAGE_LABELS else "other"

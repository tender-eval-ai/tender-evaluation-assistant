"""The Showcase's scripted reviewer (tools/seed_showcase.py): each check left to a person is
settled from the case's answer key, in the open, and a value the model missed is corrected."""
import json
from pathlib import Path

import pytest

from tools.seed_showcase import FROM_KEY, review

TRUTH = json.loads((Path(__file__).resolve().parent / "data" / "synthetic_tender" / "ground_truth.json").read_text())
A, D = TRUTH["bids"]["Tenderer_A"], TRUTH["bids"]["Tenderer_D"]


def check(field_id):
    return {"field_id": field_id, "status": "needs_review", "note": "…"}


def test_a_signature_the_model_missed_is_corrected_from_the_answer_key():
    kind, body = review(check("offer_to_be_bound.signature"), {"value": None}, "a", A)
    assert kind == "correct" and body["value"] == "signed" and FROM_KEY in body["reason"] and "page 2" in body["reason"]


@pytest.mark.parametrize("field_id, letter, bid, decision", [
    ("particulars_of_goods.rows_left_blank", "d", A, "pass"),
    ("manufacturer_letter.document", "i", A, "pass"),              # A makes the goods itself
    ("manufacturer_letter.document", "i", D, "dormant"),           # D doesn't: not settled from the key
    ("documentary_evidence.safety_data_sheet", "h", A, "dormant"),
    ("compliance_schedule.document", "n", A, "pass"),
    ("something.else", "k", A, "dormant"),
])
def test_every_other_check_is_decided_with_a_reason(field_id, letter, bid, decision):
    kind, body = review(check(field_id), {"value": "x"}, letter, bid)
    assert kind == "decide" and body["decision"] == decision and body["reason"]

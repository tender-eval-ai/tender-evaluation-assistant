"""The S4 scorer: the checker's BidResult against a hand-written answer key.

Results are built with the API's own models (backend.schemas_api), so a change to the
BidResult shape breaks these tests rather than the scorer on a real bid.
"""
import json

from backend.schemas_api import BidResult, FieldValue, PageCitation, StageSummary, Verification
from tools.key_from_ground_truth import key_from_truth
from tools.score_bid_key import format_score, load_pages, score


def fv(value, page=None, file="offer.pdf", redacted=False, verified=None) -> FieldValue:
    cite = PageCitation(doc_id="d", file=file, page=page, image_url="/x") if page else None
    check = Verification(verified=verified, method="second_read") if verified is not None else None
    return FieldValue(value=value, redacted=redacted, page=cite, verification=check)


def result(fields: dict) -> dict:
    return BidResult(tenderer="Tenderer_X", run_id="r", ruleset_version=1, fields=fields, verdicts={},
                     stage1=StageSummary(outcome="pass", items={})).model_dump(mode="json")


def item(status="present", form="price_schedule", pages=(3,), signed="", fields=None, extra=()):
    return {"status": status, "form": form, "pages": list(pages), "signed": signed, "dated": "", "chop": "",
            "redacted": "", "fields": fields or {}, "extra": list(extra), "note": ""}


def key(**items) -> dict:
    return {"schema": "bid-key-v1", "tender": "T", "frozen": {"sha256": "abc"}, "items": items}


def f(value="", page=3, redacted=False, unsure=False) -> dict:
    return {"value": value, "page": page, "redacted": redacted, "unsure": unsure}


def test_a_correct_reading_scores_in_full():
    k = key(b=item(fields={"unit_price": f("24.60"), "currency": f("HK$"), "total": f("27,109,200.00")}))
    r = result({"b": {"document": fv("Price Schedule", 3), "unit_price": fv(24.6, 3), "currency": fv("HK$", 3),
                      "total": fv(27109200.0, 3)}})
    s = score(k, r)
    assert (s["presence_correct"], s["presence_scored"]) == (1, 1)
    assert (s["page_hit"], s["page_within"], s["page_scored"]) == (1, 1, 1)
    assert s["values"] == {"compared": 3, "match": 3, "missed": 0, "mismatch": 0, "invented": 0}


def test_a_value_where_the_key_says_blacked_out_is_invented():
    """The error V4 exists to stop: a name read where the bid shows a black bar."""
    k = key(k=item(form="contact_details", fields={"tenderer_name": f(redacted=True)}))
    invented = result({"k": {"document": fv("Contact Details", 3), "tenderer_name": fv("Tenderer A", 3)}})
    honest = result({"k": {"document": fv("Contact Details", 3), "tenderer_name": fv(None, 3, redacted=True)}})
    assert score(k, invented)["values"]["invented"] == 1
    assert score(k, honest)["values"]["invented"] == 0


def test_each_value_is_counted_where_verification_sent_it():
    """A wrong value V4 accepted reaches a verdict unseen; a flagged one goes to a reviewer."""
    k = key(b=item(fields={"unit_price": f("24.60"), "currency": f("HK$"), "total": f("27,109,200.00"),
                           "dosage": f("4.3")}),
            k=item(form="contact_details", fields={"tenderer_name": f(redacted=True)}))
    r = result({"b": {"document": fv("Price Schedule", 3), "unit_price": fv(24.6, 3, verified=True),
                      "currency": fv("US$", 3, verified=False), "total": fv(27109200.0, 3, verified=False),
                      "dosage": fv(None, 3)},
                "k": {"document": fv("Contact Details", 3), "tenderer_name": fv("Tenderer A", 3, verified=True)}})
    s = score(k, r)
    assert s["verification"] == {"accepted": 2, "accepted_wrong": 1, "flagged": 2, "flagged_wrong": 1,
                                 "unchecked": 1, "unchecked_wrong": 1}
    assert s["accepted_precision"] == 0.5
    assert "2 accepted by V4, 1 of them wrong" in format_score(s)


def test_a_wrong_presence_and_wrong_pages_are_counted():
    k = key(a=item(status="absent", form="offer_to_be_bound", pages=()), b=item(pages=(5,)))
    r = result({"a": {"document": fv("Offer to be Bound", 2)},
                "b": {"document": fv("Price Schedule", 7), "unit_price": fv(4.4, 7)}})
    s = score(k, r)
    rows = {row["letter"]: row for row in s["rows"]}
    assert rows["a"]["presence_ok"] is False and rows["b"]["presence_ok"] is True
    assert (rows["b"]["page_hit"], rows["b"]["page_within"]) == (False, False)


def test_numbers_dates_and_signatures_compare_by_what_they_mean():
    k = key(b=item(fields={"unit_price": f("1. 3"), "total": f("29,278,047.5")}),
            l=item(form="noncollusive_certificate", signed="yes", fields={"date": f("14 August 2026")}),
            a=item(form="offer_to_be_bound", signed="no"))
    r = result({"b": {"document": fv("Price Schedule", 3), "unit_price": fv(1.3, 3), "total": fv(29278047.5, 3)},
                "l": {"document": fv("Certificate", 3), "date": fv("14 Aug 2026", 3), "signature": fv("signed", 3)},
                "a": {"document": fv("Offer", 3), "signature": fv("signed", 3)}})
    rows = {row["letter"]: row for row in score(k, r)["rows"]}
    assert rows["b"]["values"]["match"] == 2, "'1. 3' reads as 1.3; commas are separators"
    assert rows["l"]["values"]["match"] == 2, "a date in another format, and a signature, both agree"
    assert rows["a"]["values"]["mismatch"] == 1, "the key says unsigned; the checker saw a signature"


def test_a_value_missed_or_wrong_is_not_a_match():
    k = key(d=item(form="particulars_of_goods", fields={"country_of_origin": f("Vietnam"), "product_name": f("Ferric Chloride Solution")}))
    r = result({"d": {"document": fv("POGS", 3), "country_of_origin": fv("China", 3), "product_name": fv(None)}})
    assert score(k, r)["values"] == {"compared": 2, "match": 0, "missed": 1, "mismatch": 1, "invented": 0}


def test_items_outside_the_menu_or_not_decided_are_not_scored():
    """A form the menu lacks measures the menu, not the reader; n/a and unsure are the key's own doubt."""
    k = key(o=item(form="other", extra=[{"name": "contract_deposit_method", "value": "in cash", "page": 3}]),
            i=item(status="not_applicable", form="manufacturer_letter", pages=()),
            g=item(status="unsure", form="tender_sample_declaration"))
    s = score(k, result({}))
    assert (s["items_scored"], s["not_covered"], s["presence_scored"]) == (1, 1, 0)
    assert s["extras_outside_menu"] == 1


def test_a_multi_file_bid_matches_pages_through_pages_json(tmp_path):
    (tmp_path / "pages.json").write_text(json.dumps([{"seq": 12, "file": "sub/b.pdf", "page": 2, "image": "p0012.png"}]))
    k = key(b=item(pages=(12,)))
    r = result({"b": {"document": fv("Price Schedule", 2, file="b.pdf")}})
    s = score(k, r, load_pages(tmp_path / "pages.json"))
    assert (s["page_hit"], s["page_within"]) == (1, 1)


def test_a_key_from_the_synthetic_ground_truth_has_the_keyer_shape():
    truth = json.loads(open("test/data/synthetic_tender/ground_truth.json").read())
    k, pages = key_from_truth(truth, "Tenderer_A")
    assert k["schema"] == "bid-key-v1" and len(k["items"]) == 15
    assert k["items"]["i"]["status"] == "not_applicable", "Tenderer A makes its own goods"
    assert set(k["items"]["b"]["fields"]) >= {"unit_price", "currency", "total"}
    assert k["items"]["a"]["signed"] == "yes"
    assert len(pages) == truth["bids"]["Tenderer_A"]["pages"]

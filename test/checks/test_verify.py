"""V4 on item (l): Tenderer_A's certificate is a text page (checked verbatim, no call),
Tenderer_B's a scan (one second, independent read, compared). Both readings are kept
when they differ, and an unverified value is a reviewer's call through the bridge."""
from __future__ import annotations

from app.checks.engine_bridge import evaluate
from app.checks.extract import fields_from, reading_model
from test.checks.item_l import FIELDS, FORM, PREFIX, VERIFY
from app.checks.verify import SecondRead, agree, find_on_text, normalise, second_read, text_reader, verify_fields
from app.rulesets.schema import RuleSet
from test.checks.conftest import CASE, RULESET, fake_llm

ITEM = RuleSet.model_validate(RULESET).item("l")
A_PAGES = [{"seq": i, "doc": "offer.pdf", "page": i, "path": "", "has_text": True} for i in range(1, 13)]
B_PAGES = [{"seq": i, "doc": "offer.pdf", "page": i, "path": "", "has_text": False} for i in range(1, 17)]


def first_read(tenderer: str, page: int, **kw) -> dict:
    """Item (l) as V3 reports it: the fake's reading, with the page cited."""
    signed = kw.get("signed", True)
    signature = (kw.get("signatory", "authorised signatory") or "signature present") if signed else None
    reading = reading_model(FORM)(present=True, document="Non-collusive Tendering Certificate", tenderer_name=tenderer.replace("_", " "),
                                  signature=signature, date=kw.get("date", "14 August 2026"), redacted=list(kw.get("redacted", ())),
                                  page=page, confidence=0.92)
    refs = [p for p in (A_PAGES if tenderer == "Tenderer_A" else B_PAGES) if p["seq"] == page]
    return fields_from(FORM, reading, refs)


def verification(fields: dict, name: str) -> dict:
    return fields[f"{PREFIX}.{name}_verification"]


# ---------------------------------------------------------------- the text rules
def test_normalise_drops_case_punctuation_and_long_month_names():
    assert normalise("Tenderer_A") == "tenderer a" and normalise("12 August, 2026") == "12 aug 2026"
    assert normalise(None) == ""


def test_two_readings_agree_when_equal_contained_or_both_blank():
    assert agree("12 Aug 2026", "12 August 2026") and agree("authorised signatory", "authorised signatory of Tenderer B")
    assert agree(None, None) and not agree(None, "9 August 2026") and not agree("12 August 2026", "14 August 2026")
    assert agree("A", "Tenderer A") and not agree("A", "Tenderer_And"), "containment is by whole words"
    assert agree("signature present", "J. Wong", presence=True) and not agree(None, "J. Wong", presence=True)


def test_a_value_is_found_on_the_text_layer_verbatim_in_part_or_not_at_all():
    text = "Signed: authorised signatory of Tenderer A    Date: 14 August 2026"
    assert find_on_text("Tenderer A", text) == ("Tenderer A", 1.0)
    assert find_on_text("authorised signatory", text) == ("authorised signatory", 1.0)
    assert find_on_text("14 August 2025", text) == ("14 August", 2 / 3)
    assert find_on_text("12 August 2026", text) == (None, 0.0)
    assert find_on_text("14 May 2026", "Page 14 of 20") == (None, 0.0), "one word of three is no partial find"
    assert find_on_text("14 August 2025 at noon", text) == (None, 0.0), "two of five is less than half"
    assert find_on_text("Tenderer", "Tenderers shall sign") == (None, 0.0), "a word is not found inside another"


# ---------------------------------------------------------------- a text page: no call
def test_every_field_of_a_digital_certificate_is_verified_on_its_text_layer_with_no_call():
    llm = fake_llm("Tenderer_A")
    out = verify_fields(first_read("Tenderer_A", 10), A_PAGES, [10], VERIFY, "Tenderer_A", llm, text_reader(CASE / "bids" / "Tenderer_A"))
    assert llm.count() == 0
    for name in FIELDS:
        assert verification(out, name) == {"verified": True, "method": "text_layer", "second_value": None,
                                           "note": "found on the text layer of page 10"}, name
        assert out[f"{PREFIX}.{name}_confidence"] == 1.0
    assert out[f"{PREFIX}.date_quote"] == "14 August 2026"
    assert out[f"{PREFIX}.tenderer_name_quote"] == "Tenderer_A", "as the page has it: the header is the first hit"
    assert evaluate(ITEM, out)["outcome"] == "pass"


def test_a_date_the_text_layer_does_not_have_is_unverified_and_a_reviewers_call():
    out = verify_fields(first_read("Tenderer_A", 10, date="12 August 2026"), A_PAGES, [10], VERIFY, "Tenderer_A",
                        fake_llm("Tenderer_A"), text_reader(CASE / "bids" / "Tenderer_A"))
    v = verification(out, "date")
    assert v["verified"] is False and v["method"] == "text_layer" and v["note"] == "not on the text layer of page 10"
    assert out[f"{PREFIX}.date_confidence"] == 0.0 and f"{PREFIX}.date_quote" not in out
    assert verification(out, "signature")["verified"] is True
    verdict = evaluate(ITEM, out)
    status = {f["field_id"]: f for f in verdict["fields"]}
    assert verdict["outcome"] == "needs_review" and status[f"{PREFIX}.date"]["status"] == "needs_review"
    assert status[f"{PREFIX}.date"]["note"] == "unverified: not on the text layer of page 10"
    assert verdict["counts"]["needs_review"] == 1 and verdict["counts"]["pass"] == 3


def test_a_value_found_in_part_carries_the_fraction_found():
    out = verify_fields(first_read("Tenderer_A", 10, date="14 August 2025"), A_PAGES, [10], VERIFY, "Tenderer_A",
                        fake_llm("Tenderer_A"), text_reader(CASE / "bids" / "Tenderer_A"))
    assert out[f"{PREFIX}.date_confidence"] == 0.67 and verification(out, "date")["verified"] is False
    assert "only '14 August' of '14 August 2025'" in verification(out, "date")["note"]


def test_a_value_on_another_of_the_items_pages_moves_the_citation_there():
    out = verify_fields(first_read("Tenderer_A", 1), A_PAGES, [1, 10], VERIFY, "Tenderer_A", fake_llm("Tenderer_A"),
                        text_reader(CASE / "bids" / "Tenderer_A"))
    assert out[f"{PREFIX}.date_page"] == {"doc": "offer.pdf", "page": 10, "seq": 10}
    assert out[f"{PREFIX}.document_page"] == {"doc": "offer.pdf", "page": 1, "seq": 1}, "the heading is in the contents too"


def test_a_signature_without_a_printed_name_cannot_be_checked_on_a_text_layer():
    out = verify_fields(first_read("Tenderer_A", 10, signatory=None), A_PAGES, [10], VERIFY, "Tenderer_A",
                        fake_llm("Tenderer_A"), text_reader(CASE / "bids" / "Tenderer_A"))
    v = verification(out, "signature")
    assert v["verified"] is None and "not on the text layer" in v["note"]
    assert out[f"{PREFIX}.signature_confidence"] == 0.92, "the model's figure stays"
    assert evaluate(ITEM, out)["outcome"] == "pass", "unchecked is not unverified"


# ---------------------------------------------------------------- a scan: one second read
def test_a_scanned_certificate_is_read_a_second_time_and_agreement_verifies_it(monkeypatch):
    monkeypatch.setattr("app.checks.verify.read_png", lambda ref: b"png")
    llm = fake_llm("Tenderer_B")
    out = verify_fields(first_read("Tenderer_B", 13, date="12 August 2026"), B_PAGES, [13], VERIFY, "Tenderer_B", llm, lambda ref: "")
    assert llm.count(out_model=SecondRead) == 1 and llm.count() == 1 and len(llm.calls[0].images) == 1
    assert "12 August 2026" not in llm.calls[0].user and "authorised signatory" not in llm.calls[0].user, "independent"
    for name in FIELDS:
        v = verification(out, name)
        assert v["verified"] is True and v["method"] == "second_read", name
        assert out[f"{PREFIX}.{name}_confidence"] == 0.9, "the mean of 0.92 and 0.88"
    assert verification(out, "date")["second_value"] == "12 August 2026"
    assert evaluate(ITEM, out)["outcome"] == "pass"


def test_two_readings_that_differ_keep_both_and_go_to_the_reviewer(monkeypatch):
    monkeypatch.setattr("app.checks.verify.read_png", lambda ref: b"png")
    llm = fake_llm("Tenderer_B", second={"date": "18 August 2026"})
    out = verify_fields(first_read("Tenderer_B", 13, date="12 August 2026"), B_PAGES, [13], VERIFY, "Tenderer_B", llm, lambda ref: "")
    v = verification(out, "date")
    assert v == {"verified": False, "method": "second_read", "second_value": "18 August 2026",
                 "note": "the model read '12 August 2026'; a second, independent read found '18 August 2026'"}
    assert out[f"{PREFIX}.date_confidence"] == 0.44 and out[f"{PREFIX}.date"] == "12 August 2026", "the first value stands"
    verdict = evaluate(ITEM, out)
    assert verdict["outcome"] == "needs_review" and verdict["reasons"] == [f"unverified: {v['note']}"]


def test_a_blank_the_second_read_fills_is_not_a_disqualification(monkeypatch):
    monkeypatch.setattr("app.checks.verify.read_png", lambda ref: b"png")
    llm = fake_llm("Tenderer_B", second={"date": "9 August 2026"})
    out = verify_fields(first_read("Tenderer_B", 13, date=None), B_PAGES, [13], VERIFY, "Tenderer_B", llm, lambda ref: "")
    v = verification(out, "date")
    assert v["verified"] is False and v["second_value"] == "9 August 2026" and v["note"].startswith("the model read nothing")
    verdict = evaluate(ITEM, out)
    assert {f["field_id"]: f["status"] for f in verdict["fields"]}[f"{PREFIX}.date"] == "needs_review"
    assert verdict["outcome"] == "needs_review", "the engine said disqualified; two reads disagree, so a person decides"


def test_a_blank_both_reads_agree_on_is_verified_blank(monkeypatch):
    monkeypatch.setattr("app.checks.verify.read_png", lambda ref: b"png")
    llm = fake_llm("Tenderer_B", dated=False)
    out = verify_fields(first_read("Tenderer_B", 13, date=None), B_PAGES, [13], VERIFY, "Tenderer_B", llm, lambda ref: "")
    v = verification(out, "date")
    assert v["verified"] is True and v["second_value"] is None and "nothing either" in v["note"]
    assert evaluate(ITEM, out)["outcome"] == "needs_review", "a missing date is the reviewer's call by the rule set"


def test_a_signature_agrees_on_presence_not_wording(monkeypatch):
    monkeypatch.setattr("app.checks.verify.read_png", lambda ref: b"png")
    llm = fake_llm("Tenderer_B", second={"signature": "J. Wong, Director"})
    out = verify_fields(first_read("Tenderer_B", 13, signatory=None), B_PAGES, [13], VERIFY, "Tenderer_B", llm, lambda ref: "")
    assert out[f"{PREFIX}.signature"] == "signature present" and verification(out, "signature")["verified"] is True
    assert verification(out, "signature")["second_value"] == "J. Wong, Director"


def test_a_redacted_field_and_an_absent_certificate_are_not_checked(monkeypatch):
    monkeypatch.setattr("app.checks.verify.read_png", lambda ref: b"png")
    llm = fake_llm("Tenderer_B", redacted=("signature",))
    out = verify_fields(first_read("Tenderer_B", 13, signed=False, redacted=("signature",), date="12 August 2026"), B_PAGES, [13], VERIFY,
                        "Tenderer_B", llm, lambda ref: "")
    assert verification(out, "signature") == {"verified": None, "method": None, "second_value": None,
                                              "note": "covered by a black bar; nothing to check"}
    assert verification(out, "date")["verified"] is True and llm.count() == 1
    absent = verify_fields(fields_from(FORM, None, []), B_PAGES, [], VERIFY, "Tenderer_C", fake_llm("Tenderer_C"), lambda ref: "")
    assert all(verification(absent, n) == {"verified": None, "method": None, "second_value": None,
                                           "note": "no page to check against"} for n in FIELDS)


def test_the_second_read_names_the_fields_and_never_shows_the_first_reading(monkeypatch):
    monkeypatch.setattr("app.checks.verify.read_png", lambda ref: b"png")
    llm = fake_llm("Tenderer_B")
    readings = second_read(VERIFY, [B_PAGES[12]], "Tenderer_B", llm)
    prompt = llm.calls[0].user
    assert prompt.startswith("Offer of Tenderer_B: read these fields of form noncollusive_certificate from pages [13]:")
    assert all(f"- {n}:" in prompt for n in FIELDS) and set(readings) == set(FIELDS)
    assert "Non-collusive" not in prompt and "authorised" not in prompt


def test_a_second_read_with_no_usable_answer_flags_the_values_and_lets_the_check_go_on(monkeypatch):
    """A cloud model ran on inside one value until its output was cut, twice (2026-10-05): the
    check went on with every value of that form left for a reviewer, none passed unverified."""
    monkeypatch.setattr("app.checks.verify.read_png", lambda ref: b"png")
    llm = fake_llm("Tenderer_B")

    def unusable(*a, **kw):
        raise RuntimeError("LLM output failed schema validation after retry: EOF while parsing")
    monkeypatch.setattr(llm, "chat_json", unusable)
    fields = verify_fields(first_read("Tenderer_B", 13), B_PAGES, [13], VERIFY, "Tenderer_B", llm, text_reader(CASE / "bids" / "Tenderer_B"))
    for name in ("tenderer_name", "date"):
        v = verification(fields, name)
        assert v["verified"] is False and v["method"] == "second_read" and "no usable answer" in v["note"], name
        assert fields[f"{PREFIX}.{name}_confidence"] == 0.0

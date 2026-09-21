"""A reviewer's correction as pure rules: a value replaces the model's, "present" marks a
document there or not, a page moves the citation; and which fields still need review."""
from app.checks.corrections import correction_entries, open_reviews
from app.jobs.store import _apply

KEY = "noncollusive_certificate.date"
FIELDS = {KEY: "12 August 2026", f"{KEY}_page": {"doc": "offer.pdf", "page": 13, "seq": 13}, "noncollusive_certificate.document": None}


def test_a_value_replaces_the_models_and_a_page_moves_the_citation():
    assert correction_entries(FIELDS, KEY, value="14 August 2026") == {KEY: "14 August 2026"}
    assert correction_entries(FIELDS, KEY, page=10) == {f"{KEY}_page": {"doc": "offer.pdf", "page": 10, "seq": 10}}
    both = correction_entries(FIELDS, KEY, value="x", page=13)
    assert both == {KEY: "x", f"{KEY}_page": {"doc": "offer.pdf", "page": 13, "seq": 13}}


def test_present_marks_a_document_there_or_not():
    doc = "noncollusive_certificate.document"
    assert correction_entries(FIELDS, doc, present=True) == {doc: "present"}, "no model value: a placeholder"
    assert correction_entries(FIELDS, KEY, present=True) == {KEY: "12 August 2026"}, "the model's value stands"
    assert correction_entries(FIELDS, KEY, present=False) == {KEY: None}
    assert correction_entries(FIELDS, KEY, present=False, value="ignored") == {KEY: None}, "absent wins over a value"
    assert correction_entries({}, doc, page=4) == {f"{doc}_page": {"doc": "offer.pdf", "page": 4, "seq": 4}}


def test_nothing_given_changes_nothing_and_open_reviews_are_listed():
    assert correction_entries(FIELDS, KEY) == {}
    verdict = {"fields": [{"field_id": "a.x", "status": "pass"}, {"field_id": "a.y", "status": "needs_review"}, {"field_id": "a.z", "status": "needs_review"}]}
    assert open_reviews(verdict) == ["a.y", "a.z"] and open_reviews({}) == []


def test_a_corrected_value_is_the_persons_and_carries_no_verification_record():
    fields = {"x.date": "12 August 2026", "x.date_verification": {"verified": False, "note": "differs"},
              "x.date_page": {"doc": "offer.pdf", "page": 13, "seq": 13}}
    corrections = {"x.date": {"value": "14 August 2026", "by": "nasi", "reason": "read it myself", "model_value": "12 August 2026"},
                   "x.date_page": {"value": {"doc": "offer.pdf", "page": 14, "seq": 14}, "by": "nasi", "reason": "over the page", "model_value": None}}
    out = _apply(fields, corrections)
    assert out["x.date"] == "14 August 2026" and out["x.date_verification"] is None
    assert out["x.date_page"]["page"] == 14 and "x.date_page_verification" not in out

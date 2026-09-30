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


def test_open_reviews_walks_every_item_and_still_reads_a_single_item_verdict():
    multi = {"items": {"l": {"fields": [{"field_id": "x.a", "status": "needs_review"}, {"field_id": "x.b", "status": "pass"}]},
                       "b": {"fields": [{"field_id": "y.c", "status": "needs_review"}]}}}
    assert open_reviews(multi) == ["x.a", "y.c"]
    single = {"item": "l", "fields": [{"field_id": "x.a", "status": "disqualified"}, {"field_id": "x.b", "status": "needs_review"}]}
    assert open_reviews(single) == ["x.b"] and open_reviews({}) == []


def test_a_correction_typed_as_text_replaces_the_printed_text():
    """A person's text is what is shown and counted (#100 review)."""
    field = "price_schedule_parts_c_d.discount_7day"
    fields = {field: 2.505, f"{field}_printed": "2.505%", f"{field}_verification": {"verified": True}}
    out = _apply(fields, {field: {"value": "2.5%", "by": "nasi", "reason": "misread"}})
    assert out[field] == "2.5%" and f"{field}_printed" not in out and out[f"{field}_verification"] is None
    assert out[f"{field}_corrected"] is True


def test_a_bare_number_correction_keeps_the_printed_unit():
    """A corrected 7.5 corrects the figure, not the "HK$" printed beside it (#100 re-review)."""
    field = "price_schedule.unit_price"
    fields = {field: 7.8, f"{field}_printed": "HK$ 7.80 per kg", f"{field}_verification": {"verified": False}}
    for value in (7.5, "7.5", " 7,500.00 "):
        out = _apply(fields, {field: {"value": value, "by": "chenyu", "reason": "misread"}})
        assert out[field] == value and out[f"{field}_printed"] == "HK$ 7.80 per kg" and out[f"{field}_corrected"] is True
    assert _apply(fields, {field: {"value": None, "by": "chenyu", "reason": "not there"}}).get(f"{field}_printed") is None

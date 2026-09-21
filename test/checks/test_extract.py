"""V3 for item (l): one call, engine-ready fields with a citation, redaction kept apart from absence."""
from app.checks.extract_item_l import FIELDS, PREFIX, extract
from app.checks.resolve import ItemPages
from test.checks.conftest import fake_llm

PAGES = [{"seq": i, "doc": "offer.pdf", "page": i, "path": "", "has_text": False} for i in range(1, 17)]


def test_the_certificate_fields_carry_values_confidence_and_a_page(monkeypatch):
    monkeypatch.setattr("app.checks.extract_item_l.read_png", lambda ref: b"png")
    llm = fake_llm("Tenderer_B")
    fields = extract(PAGES, ItemPages(pages=[13], confidence=0.9), "Tenderer_B", llm)
    assert llm.count() == 1 and len(llm.calls[0].images) == 1
    assert set(fields) == {f"{PREFIX}.{n}{s}" for n in FIELDS for s in ("", "_redacted", "_confidence", "_page")}
    assert fields[f"{PREFIX}.document"] == "Non-collusive Tendering Certificate"
    assert fields[f"{PREFIX}.signature"] == "authorised signatory" and fields[f"{PREFIX}.date"] == "12 August 2026"
    assert fields[f"{PREFIX}.tenderer_name"] == "Tenderer B"
    assert fields[f"{PREFIX}.signature_page"] == {"doc": "offer.pdf", "page": 13, "seq": 13}
    assert fields[f"{PREFIX}.signature_confidence"] == 0.92 and fields[f"{PREFIX}.signature_redacted"] is False


def test_no_item_pages_means_absent_with_no_call():
    llm = fake_llm("Tenderer_C")
    fields = extract(PAGES, ItemPages(pages=[], confidence=0.3), "Tenderer_C", llm)
    assert llm.count() == 0
    assert all(fields[f"{PREFIX}.{n}"] is None and fields[f"{PREFIX}.{n}_page"] is None for n in FIELDS)


def test_a_redacted_signature_is_flagged_not_treated_as_missing(monkeypatch):
    monkeypatch.setattr("app.checks.extract_item_l.read_png", lambda ref: b"png")
    llm = fake_llm("Tenderer_B", signed=False, redacted=("signature",))
    fields = extract(PAGES, ItemPages(pages=[13], confidence=0.9), "Tenderer_B", llm)
    assert fields[f"{PREFIX}.signature"] is None and fields[f"{PREFIX}.signature_redacted"] is True
    assert fields[f"{PREFIX}.signature_page"] is not None, "a redacted field still cites its page"
    # A blank value carries no confidence, whatever the model said about the rest.
    assert fields[f"{PREFIX}.signature_confidence"] == 0.0 and fields[f"{PREFIX}.date_confidence"] == 0.92


def test_the_model_is_asked_for_its_confidence():
    """extract-l-v2: without a description the model left confidence at 0 on every live run.
    The schema the model fills must describe the field; the wording is free to change, the
    version is not without an eval."""
    from app.checks.extract_item_l import PROMPT_VERSION, Certificate

    assert PROMPT_VERSION == "extract-l-v2"
    assert Certificate.model_json_schema()["properties"]["confidence"].get("description")

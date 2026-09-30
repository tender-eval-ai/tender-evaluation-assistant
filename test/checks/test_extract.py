"""V3, one code path for every form: a fixed reading per form, engine-ready fields with a
citation, numbers coerced with their printed form kept, redaction kept apart from absence."""
from app.checks.extract import extract_form, fields_from, reading_model
from app.checks.extract_item_l import FIELDS, PREFIX, extract
from app.checks.forms import FORMS
from app.checks.resolve import ItemPages
from test.checks.conftest import fake_llm, pages_of

PAGES = [{"seq": i, "doc": "offer.pdf", "page": i, "path": "", "has_text": False} for i in range(1, 17)]


def test_the_certificate_fields_carry_values_confidence_and_a_page(monkeypatch):
    monkeypatch.setattr("app.checks.extract.read_png", lambda ref: b"png")
    llm = fake_llm("Tenderer_B")
    fields = extract(PAGES, ItemPages(pages=[13], confidence=0.9), "Tenderer_B", llm)
    assert llm.count() == 1 and len(llm.calls[0].images) == 1
    assert set(fields) == {f"{PREFIX}.{n}{s}" for n in FIELDS for s in ("", "_redacted", "_confidence", "_page")}
    assert fields[f"{PREFIX}.document"] == "Non-collusive Tendering Certificate"
    assert fields[f"{PREFIX}.signature"] == "authorised signatory" and fields[f"{PREFIX}.date"] == "12 August 2026"
    assert fields[f"{PREFIX}.tenderer_name"] == "Tenderer B"
    assert fields[f"{PREFIX}.signature_page"] == {"doc": "offer.pdf", "page": 13, "seq": 13}
    assert fields[f"{PREFIX}.signature_confidence"] == 0.92 and fields[f"{PREFIX}.signature_redacted"] is False


def test_no_form_pages_means_absent_with_no_call():
    llm = fake_llm("Tenderer_C")
    fields = extract(PAGES, ItemPages(pages=[], confidence=0.3), "Tenderer_C", llm)
    assert llm.count() == 0
    assert all(fields[f"{PREFIX}.{n}"] is None and fields[f"{PREFIX}.{n}_page"] is None for n in FIELDS)


def test_a_redacted_signature_is_flagged_not_treated_as_missing(monkeypatch):
    monkeypatch.setattr("app.checks.extract.read_png", lambda ref: b"png")
    llm = fake_llm("Tenderer_B", signed=False, redacted=("signature",))
    fields = extract(PAGES, ItemPages(pages=[13], confidence=0.9), "Tenderer_B", llm)
    assert fields[f"{PREFIX}.signature"] is None and fields[f"{PREFIX}.signature_redacted"] is True
    assert fields[f"{PREFIX}.signature_page"] is not None, "a redacted field still cites its page"


def test_the_price_schedule_reads_numbers_as_printed_and_coerces_them():
    llm = fake_llm("Tenderer_A")
    form = FORMS["price_schedule"]
    fields = extract_form(form, pages_of("Tenderer_A"), [3], "Tenderer_A", llm)
    assert llm.count() == 1 and "extract form price_schedule (Price Schedule, Part A) from pages [3]" in llm.calls[0].user
    assert fields["price_schedule.unit_price"] == 4.4 and fields["price_schedule.unit_price_printed"] == "HK$ 4.40 per kg"
    assert fields["price_schedule.quantity"] == 875000 and fields["price_schedule.quantity_printed"] == "875,000 kg"
    assert fields["price_schedule.total"] == 3850000.0 and fields["price_schedule.optimal_dosage"] == 4.3
    assert fields["price_schedule.currency"] == "HK$" and "price_schedule.currency_printed" not in fields
    assert fields["price_schedule.signature"] == "signature present"
    assert fields["price_schedule.document_page"] == {"doc": "offer.pdf", "page": 3, "seq": 3}


def test_a_reading_that_says_the_form_is_not_there_is_blank_with_no_citation():
    form = FORMS["board_resolution"]
    model = reading_model(form)
    fields = fields_from(form, model(present=False, resolution="something the model hallucinated", confidence=0.4),
                         [{"seq": 8, "doc": "offer.pdf", "page": 8, "path": ""}])
    assert all(fields[form.key(n)] is None and fields[f"{form.key(n)}_page"] is None for n in form.names)
    assert fields["board_resolution.document_confidence"] == 0.4


def test_the_reading_model_is_fixed_per_form_and_names_every_field():
    model = reading_model(FORMS["contact_details"])
    assert model is reading_model(FORMS["contact_details"]), "built once"
    props = model.model_json_schema()["properties"]
    assert {"present", "document", "tenderer_name", "contact_person", "telephone", "email", "address", "facsimile",
            "process_agent", "redacted", "page", "confidence"} == set(props)
    assert "0 to 1" in props["confidence"]["description"] and props["email"]["description"] == "the e-mail address as printed"


def test_the_prompt_asks_for_what_is_printed_and_treats_pages_as_evidence():
    from app.checks.extract import PROMPT_VERSION, SYSTEM

    assert PROMPT_VERSION == "extract-v4"
    for phrase in ("exactly as printed", "signature present", "black bar", "Never infer", "present=false", "evidence", "between 0 and 1"):
        assert phrase in SYSTEM, phrase

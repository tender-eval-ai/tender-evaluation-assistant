"""V3, one code path for every form: a fixed reading per form, engine-ready fields with a
citation, numbers coerced with their printed form kept, redaction kept apart from absence."""
from app.checks.extract import extract_form, fields_from, reading_model
from test.checks.item_l import FIELDS, PREFIX, extract
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

    assert PROMPT_VERSION == "extract-v6"
    for phrase in ("exactly as printed", "signature present", "black bar", "Never infer", "present=false", "evidence", "between 0 and 1"):
        assert phrase in SYSTEM, phrase


def test_the_redacted_list_is_bounded_but_offers_no_menu_of_names():
    """Unbounded, a small local model listed names until its tokens ran out; offered every name
    as an enum, it named nearly every field, read ones included (2026-10-05)."""
    for form in FORMS.values():
        spec = reading_model(form).model_json_schema()["properties"]["redacted"]
        assert spec["maxItems"] == len(form.read_fields) and spec["uniqueItems"] is True
        assert "enum" not in spec.get("items", {})


def test_a_value_read_wins_over_a_redacted_mark_and_a_placeholder_is_redacted():
    form = FORMS["noncollusive_certificate"]
    reading = reading_model(form).model_validate({
        "present": True, "tenderer_name": "Tenderer B Ltd", "date": "[REDACTED]", "signature": None,
        "redacted": ["tenderer_name", "signature", "not a field"]})
    fields = fields_from(form, reading, [{"seq": 13, "doc": "offer.pdf", "page": 13}])
    key = form.key
    assert fields[key("tenderer_name")] == "Tenderer B Ltd" and fields[f"{key('tenderer_name')}_redacted"] is False
    assert fields[key("date")] is None and fields[f"{key('date')}_redacted"] is True
    assert fields[key("signature")] is None and fields[f"{key('signature')}_redacted"] is True


def test_a_form_read_as_absent_on_pages_found_for_it_says_so():
    form = FORMS["offer_to_be_bound"]
    absent = reading_model(form).model_validate({"present": False})
    fields = fields_from(form, absent, [{"seq": 2, "doc": "offer.pdf", "page": 2}, {"seq": 3, "doc": "offer.pdf", "page": 3}])
    assert fields[form.key("document")] is None and fields[f"{form.key('document')}_located"] == [2, 3]
    assert f"{form.key('document')}_located" not in fields_from(form, None, []), "no pages found: nothing to say"


def test_each_value_of_a_multi_page_form_cites_the_page_it_is_printed_on(monkeypatch):
    """One page for a whole multi-page form cited every value on its first page (2026-10-05); a
    second call points each value at its page, and leaves the values as read."""
    from test.fakes import FakeLLM, Rule
    monkeypatch.setattr("app.checks.extract.read_png", lambda ref: b"png")
    form = FORMS["information_schedule"]
    pages = [{"seq": s, "doc": "offer.pdf", "page": s, "path": "", "has_text": False} for s in (21, 22, 23, 24)]
    reading = {"present": True, "page": 21, "redacted": [], "confidence": 0.9, "track_record": "5 years",
               "business_entity_type": "limited company", "event_disclosure_box": "box (a) ticked",
               "shareholders_ownership": "as listed"}
    llm = FakeLLM([Rule(reply=reading, match=r"extract form "),
                   Rule(reply={"track_record": 2, "event_disclosure_box": 24, "shareholders_ownership": 99},
                        match=r"values read from form ")])
    fields = extract_form(form, pages, [21, 22, 23, 24], "Tenderer_B", llm)
    seq = lambda name: fields[f"{form.key(name)}_page"]["seq"]  # noqa: E731
    assert seq("track_record") == 22, "the second image is page 22"
    assert seq("event_disclosure_box") == 24, "a page number of the form is taken as one"
    assert seq("business_entity_type") == 21, "no page given: the form's page"
    assert seq("shareholders_ownership") == 21, "a page outside the form: the form's page"
    assert fields[form.key("track_record")] == "5 years", "the values stay as read"
    located = next(c for c in llm.calls if "values read from form" in c.user)
    assert '"track_record": "5 years"' in located.user and "subcontractor_name" not in located.user
    assert "image 1 is page 21, image 2 is page 22" in located.user


def test_a_single_page_form_makes_no_second_call(monkeypatch):
    from test.fakes import FakeLLM, Rule
    monkeypatch.setattr("app.checks.extract.read_png", lambda ref: b"png")
    form = FORMS["price_schedule"]
    pages = [{"seq": 3, "doc": "offer.pdf", "page": 3, "path": "", "has_text": False}]
    llm = FakeLLM([Rule(reply={"present": True, "unit_price": "4.40", "page": 3}, match=r"extract form ")])
    extract_form(form, pages, [3], "Tenderer_B", llm)
    assert llm.count() == 1


def test_an_empty_string_reads_as_blank():
    form = FORMS["particulars_of_goods"]
    reading = reading_model(form).model_validate({"present": True, "manufacturer": "  ", "product_name": "Ferric chloride"})
    fields = fields_from(form, reading, [{"seq": 5, "doc": "offer.pdf", "page": 5}])
    assert fields[form.key("manufacturer")] is None and fields[f"{form.key('manufacturer')}_page"] is None
    assert fields[form.key("product_name")] == "Ferric chloride"

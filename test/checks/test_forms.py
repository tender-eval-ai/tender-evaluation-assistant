"""The closed menu of forms: one per page label that serves a schedule item, unique ids,
`document` on every form, and the way a rule-set item finds its form."""
from types import SimpleNamespace

from app.checks.forms import FORM_OF_LABEL, FORMS, form_for, form_for_title, form_of_key, forms_for_letter
from app.checks.labels import PAGE_LABELS


def test_every_label_that_serves_an_item_has_a_form_and_ids_are_the_prefixes():
    serving = {label for label, letters in PAGE_LABELS.items() if letters}
    assert serving <= set(FORM_OF_LABEL) <= set(PAGE_LABELS), "a form's label is in V1's vocabulary"
    assert all(form.names[0] == "document" for form in FORMS.values())
    assert all(form.key("document") == f"{form.id}.document" for form in FORMS.values())
    assert len({f.id for f in FORMS.values()}) == len(FORMS) and len({f.label for f in FORMS.values()}) == len(FORMS)


def test_every_schedule_letter_reaches_exactly_one_form():
    for letter in "abcdefghijklmno":
        forms = forms_for_letter(letter)
        assert len(forms) == 1, letter
    assert forms_for_letter("b")[0].id == "price_schedule" and forms_for_letter("c")[0].id == "price_schedule"
    assert forms_for_letter("m")[0].id == "price_schedule_parts_c_d" and forms_for_letter("x1") == []


def item(title="", template=None, letter="a", quote=""):
    return SimpleNamespace(template=template, title=title, letter=letter, citation=SimpleNamespace(quote=quote))


def test_an_item_finds_its_form_by_template_then_by_what_its_row_names():
    assert form_for(item("anything", template="noncollusive_certificate")).id == "noncollusive_certificate"
    assert form_for(item("The contact details of the Tenderer", letter="i")).id == "contact_details"
    assert form_for(item("Certificate", template="some_future_template",
                         quote="the essential information in the Particulars of Goods Schedule")).id == "particulars_of_goods"
    assert form_of_key("price_schedule.unit_price").id == "price_schedule" and form_of_key("nope.x") is None


def test_the_letter_does_not_choose_the_form():
    """Another tender puts other items under the same letters: (m) is the contract deposit on
    one real schedule and Parts C and D of the Price Schedule on the synthetic one."""
    assert form_for(item("Method of providing the contract deposit (Annex A)", letter="m")).id == "contract_deposit"
    assert form_for(item("Company chop on every page", letter="k")) is None, "names no form: a reviewer decides"


def test_the_row_that_names_a_form_first_wins():
    assert form_for_title("Parts C and D of the Price Schedule.").id == "price_schedule_parts_c_d"
    assert form_for_title("The unit price in Part A of the Price Schedule").id == "price_schedule"
    assert form_for_title("A certified extract of the board resolution or other documentary evidence, "
                          "the signatory of the Offer to be Bound").id == "board_resolution"
    assert form_for_title("T he Compliance Schedule").id == "compliance_schedule", "the parser splits words"
    assert form_for_title("an \u201c Offer to be Bound \u201d in Part 4").id == "offer_to_be_bound"
    assert form_for_title("Samples of the Goods, if requested").id == "tender_sample_declaration"


def test_every_synthetic_schedule_row_names_the_form_its_letter_had():
    import json
    from pathlib import Path

    located = json.loads((Path(__file__).resolve().parents[1] / "data" / "synthetic_tender_nodes" / "located.json").read_text())
    items = located["items"] if isinstance(located, dict) else located
    assert {i["letter"]: form_for_title(i["title"]).id for i in items} == \
        {i["letter"]: forms_for_letter(i["letter"])[0].id for i in items}


def test_v4_specs_follow_the_menu_and_signatures_agree_on_presence():
    specs = FORMS["price_schedule"].specs()
    assert [s.key for s in specs][:3] == ["price_schedule.document", "price_schedule.unit_price", "price_schedule.currency"]
    assert next(s for s in specs if s.key.endswith(".signature")).presence is True
    assert all(not s.presence for s in specs if not s.key.endswith(".signature"))


def test_a_field_a_reviewer_enters_is_never_asked_for_or_verified_but_is_always_reported():
    from app.checks.extract import fields_from, reading_model

    form = FORMS["tender_sample_declaration"]
    reviewer_only = {f.name for f in form.all_fields if f.by == "reviewer"}
    assert "sample_net_weight_kg" in reviewer_only and "declaration" not in reviewer_only
    assert not reviewer_only & set(reading_model(form).model_fields), "V3 never asks the model for it"
    assert not {s.key for s in form.specs()} & {form.key(n) for n in reviewer_only}, "V4 never checks it"
    reading = reading_model(form)(present=True, page=4, document="Tender Sample Declaration", declaration="we agree")
    out = fields_from(form, reading, [{"seq": 4, "doc": "offer.pdf", "page": 4}])
    assert out["tender_sample_declaration.sample_net_weight_kg"] is None, "blank until a person enters it"
    assert out["tender_sample_declaration.sample_net_weight_kg_page"] is None
    assert out["tender_sample_declaration.declaration"] == "we agree"
    assert out["tender_sample_declaration.sample_net_weight_kg_confidence"] is None, "no reading, no confidence"


def test_the_l3_field_menu_marks_what_a_reviewer_enters():
    from types import SimpleNamespace

    from app.rulesets.novel import field_menu

    menu = field_menu(SimpleNamespace(template="tender_sample_declaration", title="", citation=None))
    assert "sample_net_weight_kg (number, entered by a reviewer after the tender closes)" in menu
    assert "declaration (text)," in menu


def test_the_contract_lists_every_form_and_field():
    """docs/api_contract.md's Forms and fields table is what Nasi's templates are written against."""
    from pathlib import Path

    doc = Path(__file__).resolve().parents[2] / "docs" / "api_contract.md"
    text = doc.read_text().split("## Forms and fields")[1]
    for form in FORMS.values():
        row = next((line for line in text.splitlines() if line.startswith(f"| `{form.id}`")), None)
        assert row is not None, form.id
        assert f"`{form.label}`" in row
        for field in form.all_fields:
            assert f"`{field.name}` ({field.kind})" in row, (form.id, field.name)
            assert (f"`{field.name}` ({field.kind}) by a reviewer" in row) == (field.by == "reviewer"), (form.id, field.name)

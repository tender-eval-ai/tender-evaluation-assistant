"""The closed menu of forms: one per page label that serves a schedule item, unique ids,
`document` on every form, and the way a rule-set item finds its form."""
from types import SimpleNamespace

from app.checks.forms import FORM_OF_LABEL, FORMS, form_for, form_of_key, forms_for_letter
from app.checks.labels import PAGE_LABELS


def test_every_label_that_serves_an_item_has_a_form_and_ids_are_the_prefixes():
    serving = {label for label, letters in PAGE_LABELS.items() if letters}
    assert set(FORM_OF_LABEL) == serving
    assert all(form.names[0] == "document" for form in FORMS.values())
    assert all(form.key("document") == f"{form.id}.document" for form in FORMS.values())
    assert len({f.id for f in FORMS.values()}) == len(FORMS) and len({f.label for f in FORMS.values()}) == len(FORMS)


def test_every_schedule_letter_reaches_exactly_one_form():
    for letter in "abcdefghijklmno":
        forms = forms_for_letter(letter)
        assert len(forms) == 1, letter
    assert forms_for_letter("b")[0].id == "price_schedule" and forms_for_letter("c")[0].id == "price_schedule"
    assert forms_for_letter("m")[0].id == "price_schedule_parts_c_d" and forms_for_letter("x1") == []


def test_an_item_finds_its_form_by_template_then_by_letter():
    assert form_for(SimpleNamespace(template="noncollusive_certificate", letter="l")).id == "noncollusive_certificate"
    assert form_for(SimpleNamespace(template=None, letter="k")).id == "contact_details"
    assert form_for(SimpleNamespace(template="some_future_template", letter="d")).id == "particulars_of_goods"
    assert form_for(SimpleNamespace(template=None, letter="x1")) is None
    assert form_of_key("price_schedule.unit_price").id == "price_schedule" and form_of_key("nope.x") is None


def test_v4_specs_follow_the_menu_and_signatures_agree_on_presence():
    specs = FORMS["price_schedule"].specs()
    assert [s.key for s in specs][:3] == ["price_schedule.document", "price_schedule.unit_price", "price_schedule.currency"]
    assert next(s for s in specs if s.key.endswith(".signature")).presence is True
    assert all(not s.presence for s in specs if not s.key.endswith(".signature"))


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

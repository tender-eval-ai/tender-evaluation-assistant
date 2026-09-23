"""A form's notes and trigger are inherited when an item matches its template.

They are facts about the FORM - "needed only when the tenderer does not make the
goods itself" holds for every tender that uses that form - so the template carries
them and every matched item gets them. See checklist J2. The template id is our form
id and the rule's field one of that form's keys (`app/checks/forms.py`), as every
production template's must be.
"""
from app.rulesets.match import match_item
from app.rulesets.schema import Citation, ItemNote, Part, RuleSetItem, Template, TemplateRule


def _template() -> Template:
    return Template(
        id="manufacturer_letter",
        form_name="Manufacturer's Letter of Intent",
        notes=[ItemNote(kind="trigger", text="needed only when the tenderer does not make the goods itself")],
        condition="not manufacturer",
        consequences={"critical": {"outcomes": {"blank": {"status": "disqualified"}, "filled": {"status": "pass"}}}},
        rules=[TemplateRule(id="manufacturer_letter.present", check="document_present",
                            field="manufacturer_letter.document", consequence="critical")],
    )


def _item(**over) -> RuleSetItem:
    base = dict(letter="k", title="Manufacturer's Letter of Intent", part=Part.A,
                citation=Citation(file="tender/09 Schedules.pdf", page=1, quote="(k) Manufacturer's Letter of Intent",
                                  data_class="synthetic"),
                status="needs_input")
    return RuleSetItem(**{**base, **over})


class _LLM:
    def __init__(self, template): self.template = template
    def chat_json(self, system, user, model):  # noqa: ARG002
        return model(template=self.template)


def test_a_matched_item_inherits_the_forms_notes_and_condition():
    template = _template()
    item = match_item(_item(), {"manufacturer_letter": template}, index=None,
                      llm=_LLM("manufacturer_letter"))

    assert item.template == "manufacturer_letter"
    assert [n.text for n in item.notes] == ["needed only when the tenderer does not make the goods itself"]
    assert item.condition == "not manufacturer"


def test_an_items_own_condition_wins_but_it_still_gets_the_notes():
    """locate may read a tender-specific trigger off the schedule row; that is more
    specific than the form's default, but it does not discard the form's prose."""
    template = _template()
    item = match_item(_item(condition="on request"), {"manufacturer_letter": template},
                      index=None, llm=_LLM("manufacturer_letter"))

    assert item.condition == "on request"
    assert len(item.notes) == 1


def test_no_match_leaves_the_item_untouched():
    item = match_item(_item(), {"manufacturer_letter": _template()}, index=None, llm=_LLM("nope"))
    assert item.template is None and item.notes == [] and item.condition is None


def test_matching_again_does_not_repeat_the_forms_notes():
    template = _template()
    once = match_item(_item(), {"manufacturer_letter": template}, index=None, llm=_LLM("manufacturer_letter"))
    twice = match_item(once, {"manufacturer_letter": template}, index=None, llm=_LLM("manufacturer_letter"))
    assert len(twice.notes) == 1

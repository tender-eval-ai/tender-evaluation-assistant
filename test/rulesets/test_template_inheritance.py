"""A form's notes and trigger are inherited when an item matches its template.

They are facts about the FORM - "required only if the Tenderer is not itself the
Manufacturer" holds for every tender that uses that form - so the template carries
them and every matched item gets them. See checklist J2.
"""
from app.rulesets.match import match_item
from app.rulesets.schema import Citation, ItemNote, Part, RuleSetItem, Template, TemplateRule


def _template() -> Template:
    return Template(
        id="manufacturer_letter_of_intent",
        form_name="Manufacturer's Letter of Intent",
        notes=[ItemNote(kind="trigger", text="required only if the Tenderer is not itself the Manufacturer")],
        condition="not manufacturer",
        consequences={"critical": {"outcomes": {"blank": {"status": "disqualified"}, "filled": {"status": "pass"}}}},
        rules=[TemplateRule(id="loi.present", check="document_present", field="loi.document", consequence="critical")],
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
    item = match_item(_item(), {"manufacturer_letter_of_intent": template}, index=None,
                      llm=_LLM("manufacturer_letter_of_intent"))

    assert item.template == "manufacturer_letter_of_intent"
    assert [n.text for n in item.notes] == ["required only if the Tenderer is not itself the Manufacturer"]
    assert item.condition == "not manufacturer"


def test_an_items_own_condition_wins_but_it_still_gets_the_notes():
    """locate may read a tender-specific trigger off the schedule row; that is more
    specific than the form's default, but it does not discard the form's prose."""
    template = _template()
    item = match_item(_item(condition="on request"), {"manufacturer_letter_of_intent": template},
                      index=None, llm=_LLM("manufacturer_letter_of_intent"))

    assert item.condition == "on request"
    assert len(item.notes) == 1


def test_no_match_leaves_the_item_untouched():
    item = match_item(_item(), {"manufacturer_letter_of_intent": _template()}, index=None, llm=_LLM("nope"))
    assert item.template is None and item.notes == [] and item.condition is None

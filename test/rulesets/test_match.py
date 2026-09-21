"""L1 on the synthetic tender: one call per item with the library as a closed menu, the
chosen template copied onto the item, an invented id refused by code."""
from __future__ import annotations

from app.rulesets import match as l1
from app.rulesets.schema import ItemStatus
from test.fakes import FakeLLM, Rule


def by_item(call):
    """The scripted matcher: (l) is the certificate, (b) the price schedule, the rest none."""
    if call.user.startswith("Template menu") and "Item (l)" in call.user:
        return l1.Match(template="noncollusive_certificate", confidence=0.95, reason="names the certificate")
    if "Item (b)" in call.user:
        return l1.Match(template="price_schedule", confidence=0.9, reason="Part A of the Price Schedule")
    return l1.Match(template=None, confidence=0.8, reason="no form on the menu")


def test_one_call_per_item_and_the_menu_is_the_library(located, templates, index):
    llm = FakeLLM(rules=[Rule(reply=by_item, out_model=l1.Match)])
    out = l1.match_items(located, templates, index, llm)

    assert llm.count(out_model=l1.Match) == len(located) == 15
    menu = l1.menu_of(templates)
    assert all(menu in p for p in llm.prompts) and "- price_schedule: Price Schedule" in menu
    by_letter = {i.letter: i for i in out}
    assert by_letter["l"].template == "noncollusive_certificate" and by_letter["b"].template == "price_schedule"
    assert all(by_letter[x].template is None for x in "acdefghijkmno")


def test_a_match_copies_the_rules_and_opens_the_slots(located, templates, index):
    llm = FakeLLM(rules=[Rule(reply=by_item, out_model=l1.Match)])
    by_letter = {i.letter: i for i in l1.match_items(located, templates, index, llm)}

    cert = by_letter["l"]
    assert [r.id for r in cert.rules] == [r.id for r in templates["noncollusive_certificate"].rules]
    assert cert.slots == {} and cert.status == ItemStatus.VERIFIED, "no slots to fill: matched is verified"
    price = by_letter["b"]
    assert set(price.slots) == {"estimated_quantity", "currency"} and price.status == ItemStatus.NEEDS_INPUT
    assert all(s.value is None for s in price.slots.values())
    assert by_letter["a"].status == ItemStatus.NEEDS_INPUT and by_letter["a"].rules == []


def test_an_invented_template_id_is_refused_by_code(located, templates, index):
    llm = FakeLLM(rules=[Rule(reply=l1.Match(template="ghost_template", confidence=1.0), out_model=l1.Match)])
    out = l1.match_items(located[:2], templates, index, llm)
    assert [i.template for i in out] == [None, None]


def test_an_empty_library_makes_no_call(located, index):
    llm = FakeLLM()
    assert l1.match_items(located, {}, index, llm) == located and llm.count() == 0


def test_the_prompt_shows_the_item_and_its_cited_clauses(located, index):
    item = next(i for i in located if i.letter == "b")
    text = l1.describe(item, index)
    assert text.startswith("Item (b), Part A: (b) The one-time unit price quotation")
    assert "[09-Schedules:00-Price-Schedule:PA]" in text and "[04-Terms-of-Tender-Supplement:5]" in text

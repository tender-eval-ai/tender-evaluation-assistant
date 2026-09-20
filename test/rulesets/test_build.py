"""What a build saves: Parts merged one per Part, and a rebuild that keeps a person's work."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.rulesets import build as merge
from app.rulesets.schema import (Citation, DataClass, Edit, Gap, ItemStatus, Outcome, Part, PartSpec, RuleSet, RuleSetItem,
                                 SlotValue, TemplateRule)
from test.rulesets.conftest import NODES_DIR

NOW = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)
OWN = {"blank": Outcome(status="disqualified"), "filled": Outcome(status="pass"), "redacted": Outcome(status="needs_review")}


def cite(quote="x", node="N:1") -> Citation:
    return Citation(file="tender/09 Schedules.pdf", page=1, node_id=node, quote=quote, data_class=DataClass.SYNTHETIC)


def test_parts_are_merged_one_per_part_with_every_clause_any_run_cited():
    raw = json.loads((NODES_DIR / "located.json").read_text())["parts"]
    parts = [PartSpec.model_validate(p) for p in raw]
    assert len(parts) == 8, "locate lists a Part once per run of items"
    merged = merge.merge_parts(parts)
    assert [p.part for p in merged] == [Part.A, Part.B, Part.C]
    c = next(p for p in merged if p.part == Part.C)
    assert [x.node_id for x in c.clauses] == ["02-Interpretation-Terms-of-Tender-and-Ge:P2:16.1"]
    a = next(p for p in merged if p.part == Part.A)
    assert a.citation == parts[0].citation, "the first intro's citation"
    two = PartSpec(part=Part.A, title="Part A", citation=cite(), clauses=[cite("c1", "N:1"), cite("c2", "N:2")])
    again = PartSpec(part=Part.A, title="Part A", citation=cite("later"), clauses=[cite("c2", "N:2"), cite("c3", "N:3")])
    assert [c.node_id for c in merge.merge_parts([two, again])[0].clauses] == ["N:1", "N:2", "N:3"]


def built_items():
    cert = RuleSetItem(letter="l", title="Certificate", part=Part.A, template="noncollusive_certificate", citation=cite("(l)"),
                    rules=[TemplateRule(id="noncollusive_certificate.signed", check="signature", field="c.signature", consequence="critical")],
                    status=ItemStatus.VERIFIED)
    b = RuleSetItem(letter="b", title="Price", part=Part.A, template="price_schedule", citation=cite("(b)"),
                    slots={"estimated_quantity": SlotValue(value=880000, citation=cite("880,000 kg", "PS:(2)"), verified=True)},
                    status=ItemStatus.VERIFIED)
    a = RuleSetItem(letter="a", title="Offer", part=Part.A, template=None, citation=cite("(a)"),
                    rules=[TemplateRule(id="item_a.offer_signed", check="signature", field="item_a.offer_signature", outcomes=OWN)],
                    status=ItemStatus.NOVEL)
    return [a, b, cert]


def test_a_first_build_is_draft_one_by_the_rule_builder():
    spec = merge.merge_build(None, built_items(), [], [Gap(node_id="N:9", text="shall")], project_id="p", data_class=DataClass.SYNTHETIC,
                             model="deepseek-chat", prompt_version="match-v1+slots-v1+novel-v1")
    rs = RuleSet.model_validate(spec)
    assert rs.version == 1 and rs.status == "draft" and rs.created_by == merge.BUILDER and rs.model == "deepseek-chat"
    assert [i.letter for i in rs.items] == ["a", "b", "l"] and rs.gaps[0].reason is None


def test_a_rebuild_keeps_edited_items_corrected_slots_added_items_and_gap_reasons():
    first = RuleSet.model_validate(merge.merge_build(None, built_items(), [], [Gap(node_id="N:9", text="shall")], project_id="p",
                                                     data_class=DataClass.SYNTHETIC, model=None, prompt_version="v"))
    edit = Edit(by="nasi", at=NOW, reason="wrong quantity")
    items = {i.letter: i for i in first.items}
    items["b"] = items["b"].model_copy(update={"status": ItemStatus.EDITED, "edit": edit, "slots": {
        "estimated_quantity": items["b"].slots["estimated_quantity"].model_copy(update={"value": 875000, "origin": "manual", "verified": False,
                                                                                       "model_value": 880000, "edit": edit})}})
    items["a"] = items["a"].model_copy(update={"status": ItemStatus.EDITED, "edit": edit, "notes": []})
    x1 = RuleSetItem(letter="x1", title="Chop", part=Part.B, citation=cite("chop"), status=ItemStatus.EDITED, edit=edit,
                     rules=[TemplateRule(id="chop.every_page", check="filled", field="chop.pages", outcomes=OWN)])
    gap = first.gaps[0].model_copy(update={"reason": "covered by (e)", "edit": edit})
    existing = first.model_copy(update={"items": [items["a"], items["b"], items["l"], x1], "gaps": [gap], "version": 3, "parent_version": 2})

    rebuilt_items = built_items()
    rebuilt_items[1] = rebuilt_items[1].model_copy(update={"slots": {"estimated_quantity": SlotValue(value=890000, citation=cite(), verified=True)}})
    rebuilt_items[2] = rebuilt_items[2].model_copy(update={"title": "Certificate, re-read"})
    spec = merge.merge_build(existing.model_dump(mode="json"), rebuilt_items, [], [Gap(node_id="N:9", text="shall"), Gap(node_id="N:10", text="must")],
                             project_id="p", data_class=DataClass.SYNTHETIC, model=None, prompt_version="v")
    rs = RuleSet.model_validate(spec)
    by = {i.letter: i for i in rs.items}
    assert rs.version == 3 and rs.parent_version == 2 and rs.created_by == merge.BUILDER
    assert by["l"].title == "Certificate, re-read", "an untouched item is replaced by the new build"
    assert by["a"].status == ItemStatus.EDITED and by["a"].edit == edit, "an edited item is kept"
    slot = by["b"].slots["estimated_quantity"]
    assert slot.value == 875000 and slot.origin == "manual" and slot.model_value == 890000, "the new suggestion sits beside the person's value"
    assert by["x1"].letter == "x1", "a person's own item survives"
    assert [(g.node_id, g.reason) for g in rs.gaps] == [("N:9", "covered by (e)"), ("N:10", None)]
    assert merge.touched(by["b"]) and not merge.touched(by["l"])

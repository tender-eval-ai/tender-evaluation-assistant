"""The vendor check for one Completeness Check Schedule item, layer by layer:

    pages.py            V0  every page of the offer rendered once, no page cap
    labels.py           V1's closed vocabulary of page labels, one per schedule item
    triage.py           V1  six page images per call: label, title, summary, signed, table
    resolve.py          V2  which pages hold the item: from the labels, the model only when unsure
    extract_item_l.py   V3  the Non-collusive Tendering Certificate's fields, with citations
    engine_bridge.py    V6  a RuleSetItem (app/rulesets/schema.py) evaluated by app/engine
    vendor_check.py     the pipeline of kind "vendor_check" the worker runs

Every model call goes through app.gateway; the FakeLLM stands in for tests.
"""

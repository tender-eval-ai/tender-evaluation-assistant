"""The vendor check: one tenderer's offer read, verified and decided, every form, layer
by layer:

    pages.py            V0  every page of the offer rendered once, no page cap
    labels.py           V1's closed vocabulary of page labels
    triage.py           V1  six page images per call: label, title, summary, signed, table
    resolve.py          V2  which pages hold each form: from the labels, the model only when unsure
    forms.py            the closed menu of forms and their fields (fields.py: the flat-key vocabulary)
    extract.py          V3  each form's fields, with page citations
    verify.py           V4  every value checked against the text layer, or a second read of a scan
    agent.py            V5  a bounded search for a Part A form no page was labelled as
    engine_bridge.py    V6  a RuleSetItem (app/rulesets/schema.py) evaluated by app/engine
    corrections.py      what a reviewer's correction does to a result
    pricing.py, currency.py, reports.py   the price summary and the Word reports (S4)
    vendor_check.py     the pipeline of kind "vendor_check" the worker runs

Every model call goes through app.llm.gateway; the FakeLLM stands in for tests.
"""

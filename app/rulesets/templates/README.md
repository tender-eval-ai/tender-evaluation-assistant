# Form templates

The rule builder's template library: one JSON file per form. `app/rulesets/library.py` loads every `*.json` file here, and L1 offers them to the model as a closed menu. `RULESET_TEMPLATES_DIR` points the library somewhere else; the tests use `test/data/templates/`, which also has two examples.

- **One file per form,** named `<template id>.json`. The id is the form's id in `app/checks/forms.py` (J2).
- **The format** is `Template` in `app/rulesets/schema.py`. Every rule's `field` is a `<form>.<field>` key from `app/checks/forms.py` (J2).
- **In our own words:** no text copied from a rule file or a tender (J2).
- **It ships with the image.** The backend Dockerfile copies `app/`, this folder included. `/health` reports how many templates load, a worker that builds rule sets prints the count (or a warning) when it starts, and a build with an empty library says so in its `ruleset.built` event.

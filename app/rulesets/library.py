"""The template library: one `Template` per form, read from JSON files. Production
templates live in app/rulesets/templates/ (Nasi's), which the backend image copies with
the rest of app/; tests point RULESET_TEMPLATES_DIR at their own. A missing directory is
an empty library, not an error, but an empty library is never silent: /health reports the
count, the worker warns at start, and a rule-set build says so in its event."""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import ValidationError

from app.rulesets.schema import RuleSetItem, Template

DEFAULT_DIR = Path(__file__).resolve().parent / "templates"
EMPTY = ("the template library is empty, so every schedule item is drafted from its clauses (L3) "
         "and none is matched to a form template")


def templates_dir() -> Path:
    return Path(os.environ.get("RULESET_TEMPLATES_DIR") or DEFAULT_DIR)


def load_templates(directory: Path | None = None) -> dict[str, Template]:
    """{template id: Template} for every *.json file; the file name must equal the id."""
    directory = directory or templates_dir()
    out: dict[str, Template] = {}
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        try:
            template = Template.model_validate_json(path.read_text())
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"]) or "the file"
            raise ValueError(f"template file {path.name} is not a valid template: {where}: {first['msg']}") from exc
        if template.id != path.stem:
            raise ValueError(f"template file {path.name} holds template id {template.id!r}; the names must match")
        out[template.id] = template
    return out


def library_status(directory: Path | None = None) -> dict:
    """{count, valid, error}: how many templates load, or why the library does not. `error`
    names the file, so it is for the server's own output, not for an open route."""
    try:
        return {"count": len(load_templates(directory)), "valid": True, "error": None}
    except (ValueError, OSError) as exc:
        return {"count": 0, "valid": False, "error": str(exc)}


def template_of(item: RuleSetItem, library: dict[str, Template]) -> Template | None:
    """The template an item is judged by: its own copy when it has one (#89), so a later
    change to the library never alters an item already built; the library's otherwise (an
    item stored before the copy existed). The copy has no rules: the item carries its own."""
    if item.template is None:
        return None
    if item.template_copy is not None:
        return Template(id=item.template, form_name=item.title, slots=item.template_copy.slots,
                        consequences=item.template_copy.consequences, rules=[])
    return library.get(item.template)

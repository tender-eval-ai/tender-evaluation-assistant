"""The template library: one `Template` per form, read from JSON files. Production
templates live in app/rulesets/templates/ (Nasi's); tests point RULESET_TEMPLATES_DIR
at their own. A missing directory is an empty library, not an error."""
from __future__ import annotations

import os
from pathlib import Path

from app.rulesets.schema import Template

DEFAULT_DIR = Path(__file__).resolve().parent / "templates"


def templates_dir() -> Path:
    return Path(os.environ.get("RULESET_TEMPLATES_DIR") or DEFAULT_DIR)


def load_templates(directory: Path | None = None) -> dict[str, Template]:
    """{template id: Template} for every *.json file; the file name must equal the id."""
    directory = directory or templates_dir()
    out: dict[str, Template] = {}
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        template = Template.model_validate_json(path.read_text())
        if template.id != path.stem:
            raise ValueError(f"template file {path.name} holds template id {template.id!r}; the names must match")
        out[template.id] = template
    return out

"""Item (l), the Non-collusive Tendering Certificate, as the first form V3 read (S2). The
generic extractor (app/checks/extract.py) reads every form now; these names stay for the
routes and tests that grew up around item (l)."""
from __future__ import annotations

from app.checks.extract import PROMPT_VERSION  # noqa: F401  re-exported
from app.checks.extract import extract_form
from app.checks.forms import FORMS
from app.checks.resolve import ItemPages

FORM = FORMS["noncollusive_certificate"]
PREFIX = FORM.id
FIELDS = FORM.names
VERIFY = FORM.specs()


def extract(pages: list[dict], item_pages: ItemPages, vendor: str, llm) -> dict:
    return extract_form(FORM, pages, item_pages.pages, vendor, llm)

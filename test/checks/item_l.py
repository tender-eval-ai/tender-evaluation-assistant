"""Item (l), the Non-collusive Tendering Certificate: the first form V3 read (S2), and the
names the tests that grew up around it still use. The app reads every form through
app/checks/extract.py; this used to be app/checks/extract_item_l.py (removed at S5)."""
from __future__ import annotations

from app.checks.extract import extract_form
from app.checks.forms import FORMS
from app.checks.resolve import ItemPages

FORM = FORMS["noncollusive_certificate"]
PREFIX = FORM.id
FIELDS = FORM.names
VERIFY = FORM.specs()


def extract(pages: list[dict], item_pages: ItemPages, vendor: str, llm) -> dict:
    return extract_form(FORM, pages, item_pages.pages, vendor, llm)

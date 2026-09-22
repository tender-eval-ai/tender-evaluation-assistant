"""What a reviewer's correction does to a result's fields (S4), as pure rules the review
route applies through the store: a value replaces the model's; "present" marks a document
there or not; a page moves the citation. The model's value is kept beside every one."""
from __future__ import annotations

from typing import Any

OPEN = "needs_review"


def correction_entries(fields: dict, key: str, value: Any = None, present: bool | None = None, page: int | None = None) -> dict[str, Any]:
    """{stored key: new value} for one correction request on `key`. Nothing given: no change."""
    out: dict[str, Any] = {}
    if present is False:
        out[key] = None
    elif value is not None:
        out[key] = value
    elif present is True:
        out[key] = fields.get(key) or "present"
    if page is not None:
        old = fields.get(f"{key}_page") or {}
        out[f"{key}_page"] = {**old, "doc": old.get("doc") or "offer.pdf", "page": page, "seq": old.get("seq", page) if old.get("page") == page else page}
    return out


def item_verdicts(verdict: dict) -> dict[str, dict]:
    """The per-item verdicts of a stored verdict: `items` since S4-3; a single-item verdict
    (S2 to S4-2) keyed by its letter."""
    if not verdict:
        return {}
    if "items" in verdict:
        return verdict["items"]
    return {verdict.get("item", "l"): verdict}


def open_reviews(verdict: dict) -> list[str]:
    """The checked fields a person still has to look at."""
    return [f["field_id"] for v in item_verdicts(verdict).values() for f in v.get("fields", []) if f.get("status") == OPEN]

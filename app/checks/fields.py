"""The flat-key vocabulary of an extracted item, shared by extraction (V3), verification
(V4), the engine bridge, the store and the results route: a value under `<prefix>.<name>`
and, beside it, `_redacted`, `_confidence`, `_page` (the citation), `_quote` (the text as
found on the page's text layer) `_verification` (V4's record) and, beside a number, `_printed` (the value as printed)."""
from __future__ import annotations

META_SUFFIXES = ("_redacted", "_confidence", "_page", "_quote", "_verification", "_printed")


def is_meta(key: str) -> bool:
    """True for a key that describes a value rather than holding one."""
    return key.endswith(META_SUFFIXES)


def short_name(key: str) -> str:
    """`noncollusive_certificate.date` -> `date`."""
    return key.rsplit(".", 1)[-1]

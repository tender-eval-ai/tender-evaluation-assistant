"""Signed, short-lived page-image URLs: a browser opens them as plain links, so the API
key never appears in a query string. The signature covers project, document, page and
expiry, and the highlight when the link carries one; the key is IMAGE_SIGNING_KEY, else
the API key, else a per-process secret."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlencode

_PROCESS_SECRET = secrets.token_hex(32)
DEFAULT_TTL = 15 * 60


def _key() -> bytes:
    return (os.environ.get("IMAGE_SIGNING_KEY") or os.environ.get("API_KEY") or _PROCESS_SECRET).encode()


def sign(pid: str, doc_id: str, page: int, exp: int, highlight: str | None = None) -> str:
    """A link without a highlight signs exactly what it always did, so links already
    handed out keep verifying."""
    msg = f"{pid}/{doc_id}/{page}/{exp}"
    if highlight:
        msg += "/highlight=" + hashlib.sha256(highlight.encode()).hexdigest()
    return hmac.new(_key(), msg.encode(), hashlib.sha256).hexdigest()[:32]


def verify(pid: str, doc_id: str, page: int, exp: int | None, sig: str | None, highlight: str | None = None) -> bool:
    """True for a link signed with this highlight. A page-only signature also passes
    with a highlight a client appended itself: the page is already authorised and the
    highlight only marks text on it. That is the pre-signed-highlight behaviour, kept
    until the web UI uses the signed `image_url` as given."""
    if not exp or not sig or exp < int(time.time()):
        return False
    if highlight and hmac.compare_digest(sign(pid, doc_id, page, exp, highlight), sig):
        return True
    return hmac.compare_digest(sign(pid, doc_id, page, exp), sig)


def image_url(pid: str, doc_id: str, page: int, highlight: str | None = None, ttl: int = DEFAULT_TTL) -> str:
    exp = int(time.time()) + ttl
    query = {"exp": exp, "sig": sign(pid, doc_id, page, exp, highlight)}
    if highlight:
        query["highlight"] = highlight
    return f"/projects/{pid}/documents/{doc_id}/pages/{page}/image?{urlencode(query)}"

"""Signed, short-lived page-image URLs: a browser opens them as plain links, so the API
key never appears in a query string. The signature covers project, document, page and
expiry; the key is IMAGE_SIGNING_KEY, else the API key, else a per-process secret."""
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


def sign(pid: str, doc_id: str, page: int, exp: int) -> str:
    return hmac.new(_key(), f"{pid}/{doc_id}/{page}/{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def verify(pid: str, doc_id: str, page: int, exp: int | None, sig: str | None) -> bool:
    if not exp or not sig or exp < int(time.time()):
        return False
    return hmac.compare_digest(sign(pid, doc_id, page, exp), sig)


def image_url(pid: str, doc_id: str, page: int, highlight: str | None = None, ttl: int = DEFAULT_TTL) -> str:
    exp = int(time.time()) + ttl
    query = {"exp": exp, "sig": sign(pid, doc_id, page, exp)}
    if highlight:
        query["highlight"] = highlight
    return f"/projects/{pid}/documents/{doc_id}/pages/{page}/image?{urlencode(query)}"

"""Google Cloud auth for Vertex AI's OpenAI-compatible endpoint.

Vertex does not take API keys: requests carry a short-lived OAuth bearer token from
Application Default Credentials (`gcloud auth application-default login` on a
workstation, the attached service account on Cloud Run). Tokens expire after an
hour, and the pipeline's parallel fan-out calls the model from several threads, so
the refresh is guarded by a lock and done ahead of expiry.
"""
from __future__ import annotations

import datetime as _dt
import threading

VERTEX_HOST = "aiplatform.googleapis.com"
SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
REFRESH_MARGIN = _dt.timedelta(minutes=5)


def is_vertex(base_url: str) -> bool:
    return VERTEX_HOST in base_url


class ADCToken:
    """Thread-safe bearer-token provider over Application Default Credentials.
    `credentials` may be injected (tests); otherwise google-auth is imported lazily so
    the package is only needed when a Vertex entry is actually in a chain."""

    def __init__(self, credentials=None):
        self._creds = credentials
        self._lock = threading.Lock()
        self.refreshes = 0

    def _load(self):
        import google.auth
        creds, _project = google.auth.default(scopes=list(SCOPES))
        return creds

    def _stale(self) -> bool:
        c = self._creds
        if not getattr(c, "valid", False) or not getattr(c, "token", None):
            return True
        expiry = getattr(c, "expiry", None)      # google-auth: naive datetime in UTC
        now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
        return bool(expiry) and expiry - now < REFRESH_MARGIN

    def token(self) -> str:
        with self._lock:
            if self._creds is None:
                self._creds = self._load()
            if self._stale():
                import google.auth.transport.requests
                self._creds.refresh(google.auth.transport.requests.Request())
                self.refreshes += 1
            return self._creds.token

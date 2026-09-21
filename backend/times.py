"""One rule for every timestamp the API sends: an ISO-8601 datetime in UTC (checklist
I1.17). The stores keep epoch seconds; psycopg returns them as Decimal."""
from __future__ import annotations

from datetime import datetime, timezone


def when(value) -> datetime | None:
    """Epoch seconds (float or Decimal) or an already-built datetime; None stays None."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromtimestamp(float(value), tz=timezone.utc)

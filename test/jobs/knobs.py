"""Per-scenario settings (delay, faults, page counts, the extra step). Read from the
environment, overridden by the JSON file named by HARNESS_KNOBS when it exists, so a
long-lived worker process started before a scenario still sees that scenario's values.
The harness writes the file; workers never write it."""
from __future__ import annotations

import json
import os


def get(name: str, default: str | None = None) -> str | None:
    path = os.environ.get("HARNESS_KNOBS")
    if path and os.path.exists(path):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if name in data:
            return None if data[name] is None else str(data[name])
    return os.environ.get(name, default)

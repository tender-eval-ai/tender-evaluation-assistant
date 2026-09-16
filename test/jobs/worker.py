"""Worker subprocess entry point: python -m test.jobs.worker <adapter> <run_id>.
Started by an adapter; the harness kills it with SIGKILL or SIGTERM to simulate a
crash or a deploy."""
from __future__ import annotations

import sys

from test.jobs.adapters import load


def main(argv: list[str]) -> int:
    adapter_name, run_id = argv[1], argv[2]
    load(adapter_name).execute(run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

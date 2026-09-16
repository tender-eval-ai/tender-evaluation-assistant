"""Worker process: python -m spikes.common.worker_main <tasks module> <name>.
Imports the variant's task module (which builds the Procrastinate app) and runs a
worker with the harness's short heartbeat settings."""
from __future__ import annotations

import importlib
import sys

from spikes.common.queue import HEARTBEAT, QUEUE, STALLED_AFTER


def main(argv: list[str]) -> int:
    module = importlib.import_module(argv[1])
    module.app.run_worker(queues=[QUEUE], name=argv[2], concurrency=2, wait=True,
                          fetch_job_polling_interval=0.5, update_heartbeat_interval=HEARTBEAT,
                          stalled_worker_timeout=STALLED_AFTER, install_signal_handlers=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

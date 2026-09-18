"""Worker process: python -m app.jobs.worker [--name N] [--concurrency C]
[--pipelines mod,mod] [--no-migrate] [--no-sweep].

Imports the pipeline modules (they register their kinds), applies pending migrations
and Procrastinate's schema, starts the sweeper thread, then runs jobs from the
`checks` queue until SIGTERM, which drains the running jobs first."""
from __future__ import annotations

import argparse
import os
import socket
import sys

from app.jobs import registry
from app.jobs.queue import QUEUE, Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default=f"{socket.gethostname()}-{os.getpid()}")
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--pipelines", default=os.environ.get("JOB_PIPELINES", ""),
                        help="comma-separated modules that register pipelines")
    parser.add_argument("--no-migrate", action="store_true")
    parser.add_argument("--no-sweep", action="store_true")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    registry.load(args.pipelines.split(","))
    from app import db
    from app.jobs import tasks
    from app.jobs.sweeper import Sweeper

    if not args.no_migrate:
        db.prepare(tasks.app, settings.dsn)
    if not args.no_sweep:
        Sweeper(settings).start()
    print(f"[worker] {args.name}: pipelines {registry.kinds()}, queue {QUEUE}", file=sys.stderr)
    tasks.app.run_worker(queues=[QUEUE], name=args.name, concurrency=args.concurrency or settings.concurrency,
                         wait=True, fetch_job_polling_interval=settings.poll,
                         update_heartbeat_interval=settings.heartbeat, stalled_worker_timeout=settings.stalled_after,
                         install_signal_handlers=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

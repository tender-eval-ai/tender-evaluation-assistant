"""Procrastinate job queue with a job_steps progress table and a status-column pause."""
from __future__ import annotations

from pathlib import Path

import psycopg

from spikes.common import base_adapter, queue as q, store as store_mod
from spikes.common.base_adapter import QueueBackedAdapter
from spikes.queue import tasks


class ProcrastinateAdapter(QueueBackedAdapter):
    name = "queue"
    tasks_module = "spikes.queue.tasks"
    services = "Postgres (Procrastinate tables + q_steps)"
    glue_files = [str(Path(__file__)), str(Path(tasks.__file__)),
                  str(Path(base_adapter.__file__)), str(Path(q.__file__)), str(Path(store_mod.__file__))]

    def __init__(self):
        super().__init__(tasks)

    def _extra_setup(self) -> None:
        with psycopg.connect(self.store.dsn, autocommit=True) as c:
            c.execute(tasks.STEPS_SQL)
            c.execute("truncate q_steps")

    def _on_rerun(self, run: dict) -> None:
        with psycopg.connect(self.store.dsn, autocommit=True) as c:
            c.execute("delete from q_steps where run_id=%s", (run["run_id"],))

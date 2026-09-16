"""LangGraph + Postgres checkpointer, on the shared Procrastinate run queue. Progress is
the checkpointer's; the pause is interrupt(); everything else is the shared base."""
from __future__ import annotations

from pathlib import Path

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver

from spikes.common import base_adapter, queue as q, store as store_mod
from spikes.common.base_adapter import QueueBackedAdapter
from spikes.langgraph import tasks


class LangGraphAdapter(QueueBackedAdapter):
    name = "langgraph"
    tasks_module = "spikes.langgraph.tasks"
    services = "Postgres (Procrastinate tables + LangGraph checkpoints)"
    glue_files = [str(Path(__file__)), str(Path(tasks.__file__)), str(Path(__file__).with_name("graph.py")),
                  str(Path(base_adapter.__file__)), str(Path(q.__file__)), str(Path(store_mod.__file__))]

    def __init__(self):
        super().__init__(tasks)

    def _extra_setup(self) -> None:
        with PostgresSaver.from_conn_string(self.store.dsn) as saver:   # once, here: concurrent setup() races
            saver.setup()
        with psycopg.connect(self.store.dsn, autocommit=True) as c:      # fresh checkpoints per scenario
            c.execute("truncate checkpoint_writes, checkpoint_blobs, checkpoints")

    # a re-run gets a new thread id (attempt + 1), so nothing to forget

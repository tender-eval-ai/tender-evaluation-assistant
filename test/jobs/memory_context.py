"""A pipeline context that keeps progress and checkpoints in memory, for tests that run
a pipeline without Postgres or a worker."""
from __future__ import annotations


class MemoryContext:
    def __init__(self, run: dict | None = None, ruleset: tuple[int, dict] | None = None):
        self.run = run or {"run_id": "r1", "project": "p", "tenderer": "t", "kind": "k"}
        self.data: dict = {}
        self.done: list[str] = []
        self._ruleset = ruleset
        self.events: list[tuple] = []

    def progress(self, step, done, total, unit="pages"):
        self.events.append(("progress", step, done, total))

    def checkpoint(self, **data):
        self.data.update(data)
        self.events.append(("checkpoint", dict(data)))

    def complete(self, step, data):
        if data:
            self.data.update(data)
        self.done.append(step)
        self.events.append(("complete", step))

    def paused(self, step, reason):
        self.events.append(("paused", step, reason))

    def resumed(self, step):
        self.events.append(("resumed", step))

    def ruleset(self):
        return self._ruleset

    def confirm(self, spec: dict, version: int = 1) -> None:
        self._ruleset = (version, spec)

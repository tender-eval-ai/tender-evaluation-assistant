"""Pipelines by kind. A pipeline module registers itself on import; the worker imports
the modules named on its command line, the API the ones it needs for `decide`."""
from __future__ import annotations

import importlib

from app.jobs.models import Pipeline

_PIPELINES: dict[str, Pipeline] = {}


def register(pipeline: Pipeline) -> Pipeline:
    _PIPELINES[pipeline.kind] = pipeline
    return pipeline


def get(kind: str) -> Pipeline:
    try:
        return _PIPELINES[kind]
    except KeyError:
        raise KeyError(f"no pipeline registered for kind {kind!r}; known: {sorted(_PIPELINES)}") from None


def kinds() -> list[str]:
    return sorted(_PIPELINES)


def load(modules: list[str]) -> None:
    for name in modules:
        if name:
            importlib.import_module(name)

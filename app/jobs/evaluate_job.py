"""The pipeline of kind "evaluate": every stored result of a project re-decided by the
engine against one confirmed rule-set version, no model call. The version comes in the
run's seeded step data. Fields a new rule needs that were never extracted read as blank
for now; the extraction of missing fields arrives with V3 for every document type (S4-3)."""
from __future__ import annotations

from app.jobs import registry
from app.jobs.models import EVALUATE, Context, Pipeline, Step


def redecide(ctx: Context):
    store = ctx.store
    pid = ctx.run["project"]
    version = int(ctx.data["version"])
    spec = store.get_version(pid, version)
    if spec is None or spec.get("status") != "confirmed":
        raise RuntimeError(f"rule set version {version} of {pid} is not a confirmed version")
    ctx.progress("redecide", 0, 1, "steps")
    rows = store.redecide(pid, version, spec, lambda kind: registry.get(kind).decide)
    for row in rows:
        if row["changed"]:
            store.event("result.reevaluated", pid, row["tenderer"], row["before"], row["after"], EVALUATE.strip("_"),
                        f"rule set v{version}")
    return {"reevaluated": [{"tenderer": r["tenderer"], "changed": r["changed"]} for r in rows]}


PIPELINE = registry.register(Pipeline(kind="evaluate", steps=[Step("redecide", redecide, "steps")], fields_key=None))

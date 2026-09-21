"""FastAPI backend: the evaluation pipeline as a project-based service.

Project lifecycle (mirrors the CLI checkpoints, which stay human-editable):

    POST /projects                          create a project
    POST /projects/{id}/tender              upload tender document PDFs
    POST /projects/{id}/bids/{tenderer}     upload one tenderer's offer PDFs
    GET/PUT /projects/{id}/rubric           review / edit the rubric  (human checkpoint)
    POST /projects/{id}/run                 orchestrated run (LangGraph): derive rubric
                                            -> PAUSE -> extract bids (parallel, verified,
                                            evidence-searched) -> PAUSE -> evaluate, report
    POST /projects/{id}/resume              continue past a pause (edits made via the PUT
                                            endpoints while paused are picked up)
    GET  /projects/{id}/graph               pending checkpoint, progress, corrections
    POST /projects/{id}/evaluate            re-evaluate from the stored extractions
                                            (deterministic; no LLM)
    GET  /projects/{id}/status              poll background job state
    GET  /projects/{id}/evaluation          full EvaluationResult JSON
    GET  /projects/{id}/usage               tokens, calls, seconds and $ per bid
    GET  /projects/{id}/reports[/{name}]    list / download the Word deliverables
    PUT  /projects/{id}/bids/{tenderer}/extraction   inject or correct an extraction

S2 routes (docs/api_contract.md; they need DATABASE_URL, the queue's Postgres):
    GET/PUT /projects/{id}/ruleset[/draft], POST .../ruleset/confirm, GET .../ruleset/versions
    POST /projects/{id}/checks              one job per tenderer on the worker
    GET  /projects/{id}/jobs[/{job_id}]     follow them
    GET  /projects/{id}/bids/{t}/results    fields with citations, verdicts, cost
    GET  /projects/{id}/documents[/{doc_id}/pages[/{n}/image]]   the viewer; images by signed URL
    GET  /projects/{id}/events              the audit log

Data layout under $DATA_DIR/projects/<id>/:
    meta.json  tender/*.pdf  bids/<tenderer>/*.pdf
    work/{rubric.json, bids/<tenderer>.json, evaluation.json, reports/*.docx, cache/}
meta.json carries "synthetic": true for fully synthetic/sanitized sets — the only
projects the MCP server (mcp_server/) will show to a cloud-driven client.

Auth: if the API_KEY env var is set, every request (except /health) must send it in the
X-API-Key header. Always set it on any machine that is not localhost-only.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Config, load_dotenv
from backend import deps, jobs

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
deps.configure()   # re-read DATA_DIR / INBOX_DIR / API_KEY (tests reload this module after changing them)

from backend import errors  # noqa: E402
from backend.routes import checks, documents, events, projects, reports, results, review, rubric, rulesets, runs, viewer  # noqa: E402

# Re-exported: tests and scripts reach these through backend.api.
PROJECTS = deps.PROJECTS
API_KEY = deps.API_KEY
_project_dir = deps._project_dir
_set_status = deps._set_status
_get_status = deps._get_status
_running = jobs._running          # the same set the job runner uses
jobs._running.clear()             # a (re)import starts with no job running, as before
deps.reset_runner()               # and with no open queue connection from a previous import

app = FastAPI(title="Tender Evaluation Assistant API", version="0.1.0")

# The UI's folder picker uploads from the browser straight to this API (the Streamlit
# server never proxies the files), which is a cross-origin request from the UI's port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

errors.install(app)
errors.document(app)
jobs._reset_interrupted_jobs()


@app.get("/health")
def health() -> dict:
    cfg = Config()
    return {"ok": True, "text_model": cfg.text_model, "vision_model": cfg.vision_model,
            "auth_required": bool(deps.API_KEY)}


for router in (projects.router, rubric.router, documents.router, runs.router, results.router, reports.router,
               rulesets.router, checks.router, review.router, viewer.keyed, viewer.router, events.router):
    app.include_router(router)

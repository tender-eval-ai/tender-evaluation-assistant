"""FastAPI backend: the routes of docs/api_contract.md.

    POST/GET /projects, GET/DELETE /projects/{pid}      projects (routes/projects.py)
    POST /projects/{pid}/tender, /bids/{tenderer}       uploads; POST /import, GET /inbox
    GET/PUT/PATCH/POST /projects/{pid}/ruleset...      the rule set: build, edit, versions, confirm
    POST /projects/{pid}/checks, GET .../jobs           one vendor_check job per tenderer on the worker
    GET  /projects/{pid}/bids/{t}/results               fields with citations, verdicts, cost
    PATCH .../fields/{letter}/{field}, POST .../review/confirm, POST /evaluate   the review
    GET  /projects/{pid}/price-summary, /evaluation, /reports[/{name}]           S4
    GET  /projects/{pid}/documents[/{doc_id}/pages[/{n}/image]]                  the viewer
    GET  /projects/{pid}/events                          the audit log

The rule-set, check and review routes need DATABASE_URL (the queue's Postgres); the jobs
themselves run on the worker (app/jobs). Files live under $DATA_DIR/projects/<id>/:
meta.json, tender/*.pdf, bids/<tenderer>/*.pdf, and work/ (rendered pages, node tables).

Auth: if API_KEY is set, every request except /health and a signed page-image link must
send it in the X-API-Key header. Always set it on any machine that is not localhost-only.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Config, load_dotenv
from app.rulesets.library import library_status
from backend import deps

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
deps.configure()   # re-read DATA_DIR / INBOX_DIR / API_KEY (tests reload this module after changing them)

from backend import errors  # noqa: E402
from backend.routes import checks, events, pricing, projects, review, rulesets, viewer  # noqa: E402

# Re-exported: tests and scripts reach these through backend.api.
PROJECTS = deps.PROJECTS
API_KEY = deps.API_KEY
_project_dir = deps._project_dir
deps.reset_runner()               # a (re)import starts with no open queue connection

app = FastAPI(title="Tender Evaluation Assistant API", version="0.1.0")


@app.middleware("http")
async def upload_limit(request, call_next):
    """An upload's size is checked before its body is read: FastAPI parses a multipart body,
    spooling every file to disk, before the route runs, so a check inside the route would
    come after the disk was already used. A body without a length is refused. Added before
    CORS, so CORS stays the outer layer and a refusal still carries its headers."""
    if request.method == "POST" and deps.UPLOAD_PATH.match(request.url.path):
        length, limit = request.headers.get("content-length"), deps.max_upload_bytes()
        if length is None:
            return errors.error_response(411, "length_required", "an upload must say its length (Content-Length)")
        if not length.isdigit() or int(length) > limit:
            return errors.error_response(413, "too_large", f"the upload is larger than the {limit / (1024 * 1024):.3g} MB limit")
    return await call_next(request)


# In development the UI runs on its own port and calls this API cross-origin; behind nginx
# (compose, Azure) it is same-origin and CORS is moot.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

errors.install(app)
errors.document(app)


# Open without the key, so it names no path and no error text: the template count, and
# whether the library loads at all (the worker's start-up line says why not).
@app.get("/health")
def health() -> dict:
    cfg = Config()
    templates = library_status()
    return {"ok": True, "text_model": cfg.text_model, "vision_model": cfg.vision_model,
            "auth_required": bool(deps.API_KEY), "templates": templates["count"], "templates_valid": templates["valid"]}


for router in (projects.router, rulesets.router, checks.router, review.router, pricing.router, viewer.keyed, viewer.router,
               events.router):
    app.include_router(router)

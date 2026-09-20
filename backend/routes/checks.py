"""The Stage I and II window's jobs and results: start a check per tenderer, follow the
jobs, read a tenderer's result."""
from __future__ import annotations

import base64
from collections import defaultdict

from fastapi import APIRouter, Depends

from app.checks.extract_item_l import PREFIX as ITEM_L_PREFIX
from app.ingest import QuoteBox, locate_quote
from app.jobs.models import RunStatus, is_project_run
from backend import deps, signing
from backend.errors import ApiError
from backend.times import when
from backend.schemas_api import (BidResult, CheckedField, CheckRequest, CheckResponse, FieldValue, Job, JobPage,
                                 PageCitation, StageSummary, Verdict)

router = APIRouter(dependencies=[Depends(deps.require_key)])

ITEM_OF_PREFIX = {ITEM_L_PREFIX: "l"}


def _job(s: RunStatus, created_at: float | None = None) -> Job:
    return Job(job_id=s.run_id, kind=s.kind, project=s.project, tenderer=None if is_project_run(s.tenderer) else s.tenderer,
               state=s.state, step=s.step,
               progress=s.progress or {}, attempt=s.attempt, error=s.error, ruleset_version=s.ruleset_version,
               created_at=when(created_at or s.updated_at), updated_at=when(s.updated_at))


@router.post("/projects/{pid}/checks", status_code=202)
def start_checks(pid: str, req: CheckRequest | None = None, user: str = Depends(deps.acting_user)) -> CheckResponse:
    """One job per tenderer against the latest confirmed rule set (open question 3:
    latest confirmed, `?version=` only on evaluate)."""
    pdir = deps._project_dir(pid)
    runner = deps.runner()
    if runner.store.latest_confirmed(pid) is None:
        raise ApiError(409, "unconfirmed_ruleset", f"project {pid} has no confirmed rule set; confirm one first")
    uploaded = sorted(p.name for p in (pdir / "bids").iterdir() if p.is_dir())
    tenderers = (req.tenderers if req and req.tenderers else uploaded)
    unknown = [t for t in tenderers if t not in uploaded]
    if unknown:
        raise ApiError(404, "not_found", f"no offer uploaded for: {', '.join(unknown)}", {"tenderers": unknown})
    active = {t: runner.store.active_run(pid, t) for t in tenderers}
    busy = {t: r for t, r in active.items() if r}
    if busy:
        raise ApiError(409, "conflict", f"a check is already running for: {', '.join(sorted(busy))}", {"job_ids": busy})
    job_ids = {t: runner.start(pid, t, "vendor_check") for t in tenderers}
    runner.store.event("checks.started", pid, None, None, {"job_ids": job_ids}, user)
    return CheckResponse(job_ids=job_ids)


def _cursor(job: Job) -> str:
    return base64.urlsafe_b64encode(f"{job.created_at.isoformat()}|{job.job_id}".encode()).decode()


@router.get("/projects/{pid}/jobs")
def list_jobs(pid: str, limit: int = 100, cursor: str | None = None) -> JobPage:
    deps._project_dir(pid)
    limit = max(1, min(limit, 1000))
    runs = deps.runner().runs(pid)
    jobs = [_job(s) for s in runs]
    if cursor:
        after = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)[1]
        ids = [j.job_id for j in jobs]
        jobs = jobs[ids.index(after) + 1:] if after in ids else jobs
    page, rest = jobs[:limit], jobs[limit:]
    return JobPage(items=page, next_cursor=_cursor(page[-1]) if rest else None)


@router.get("/projects/{pid}/jobs/{job_id}")
def get_job(pid: str, job_id: str) -> Job:
    deps._project_dir(pid)
    try:
        s = deps.runner().status(job_id)
    except KeyError:
        raise ApiError(404, "not_found", f"job {job_id} not found")
    if s.project != pid:
        raise ApiError(404, "not_found", f"job {job_id} not found in project {pid}")
    return _job(s)


def _bid_result(pid: str, pdir, run: dict, result, steps: dict) -> BidResult:
    docs = {d["file"]: d for d in deps.documents_of(pdir) if d["tenderer"] == run["tenderer"]}

    located: dict[tuple, QuoteBox | None] = {}

    def cite(page_ref: dict | None, text=None) -> PageCitation | None:
        """The page a value was read from; with `text` found on its text layer, also the
        quote, its box and a signed highlighted image link."""
        if not page_ref or page_ref.get("doc") not in docs:
            return None
        d, page = docs[page_ref["doc"]], page_ref["page"]
        at = None
        if isinstance(text, str) and len(text.strip()) >= 4:
            k = (d["doc_id"], page, text)
            if k not in located:
                located[k] = locate_quote(d["path"], page - 1, text)
            at = located[k]
        if at is None:
            return PageCitation(doc_id=d["doc_id"], file=d["file"], page=page,
                                image_url=signing.image_url(pid, d["doc_id"], page))
        return PageCitation(doc_id=d["doc_id"], file=d["file"], page=page, quote=at.quote, box=list(at.box),
                            page_size=list(at.page_size), image_url=signing.image_url(pid, d["doc_id"], page, at.quote))

    fields: dict[str, dict[str, FieldValue]] = defaultdict(dict)
    for key, value in result.fields.items():
        if any(key.endswith(s) for s in ("_redacted", "_confidence", "_page", "_quote")):
            continue
        prefix, _, name = key.rpartition(".")
        letter = ITEM_OF_PREFIX.get(prefix)
        if not letter:
            continue
        correction = result.corrections.get(key)
        page_ref = (result.corrections.get(f"{key}_page") or {}).get("value") or result.fields.get(f"{key}_page")
        shown = correction["value"] if correction else value
        fields[letter][name] = FieldValue(
            value=shown,
            redacted=bool(result.fields.get(f"{key}_redacted")),
            confidence=result.fields.get(f"{key}_confidence"),
            page=cite(page_ref, result.fields.get(f"{key}_quote") or shown),
            correction=correction, model_value=value if correction else None)
    v = result.verdict
    # The engine's own "field" is display text ("tenderer name") and may be reworded; the
    # contract's `field` is the key into BidResult.fields[letter], which is built above
    # from the same field_id, so derive it the same way rather than from the engine.
    checks = [CheckedField(field_id=f["field_id"], field=f["field_id"].rsplit(".", 1)[-1], status=f["status"], note=f.get("note"), redacted=bool(f.get("redacted")),
                           stage=f.get("stage", "I"), follow_up=f.get("follow_up")) for f in v.get("fields", [])]
    evidence = [c for c in (cite(f.get("page"), f.get("value")) for f in v.get("fields", [])) if c]
    letter = v.get("item", "l")
    verdict = Verdict(outcome=v["outcome"], worst=v.get("worst", v["outcome"]), part=v["part"], rule_ids=v["rule_ids"],
                      reason="; ".join(v.get("reasons", [])), checks=checks, evidence=evidence)
    return BidResult(tenderer=run["tenderer"], run_id=run["run_id"], ruleset_version=result.ruleset_version,
                     fields=dict(fields), verdicts={letter: verdict},
                     stage1=StageSummary(outcome=v["outcome"], items={letter: v["outcome"]}),
                     cost=steps.get("data", {}).get("cost") or {}, review_confirmed_by=result.review_confirmed_by)


@router.get("/projects/{pid}/bids/{tenderer}/results")
def bid_results(pid: str, tenderer: str, version: int | None = None) -> BidResult:
    pdir = deps._project_dir(pid)
    runner = deps.runner()
    run = runner.store.latest_run(pid, tenderer, done_only=True)
    if run is None:
        raise ApiError(404, "not_found", f"no finished check for {tenderer} in {pid}")
    result = runner.results(run["run_id"])
    if result is None:
        raise ApiError(404, "not_found", f"no result stored for {tenderer}")
    if version is not None and result.ruleset_version != version:
        raise ApiError(404, "not_found", f"{tenderer}'s result is at rule-set version {result.ruleset_version}, not {version}")
    return _bid_result(pid, pdir, run, result, runner.store.steps(run["run_id"]))

"""The S4 review routes: a reviewer's correction of a field, the confirmation of a
tenderer's review, the engine-only re-evaluation of every result against a rule-set
version, and the retry of a failed job. Every change is an event with the person's reason."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.checks.corrections import correction_entries, item_verdicts, open_reviews
from app.checks.engine_bridge import by_reviewer
from app.checks.forms import form_for
from app.jobs.models import EVALUATE
from backend import deps
from backend.errors import ApiError
from backend.routes.checks import _bid_result
from app.rulesets.schema import RuleSet
from backend.schemas_api import BidResult, CorrectionRequest, EvaluateRequest, JobStarted

router = APIRouter(dependencies=[Depends(deps.require_key)])

def _checked(runner, pid: str, tenderer: str):
    """The tenderer's latest finished run, its result and the rule set it was decided against."""
    run = runner.store.latest_run(pid, tenderer, done_only=True)
    if run is None:
        raise ApiError(404, "not_found", f"no finished check for {tenderer} in {pid}")
    result = runner.results(run["run_id"])
    if result is None:
        raise ApiError(404, "not_found", f"no result stored for {tenderer}")
    return run, result, runner.store.get_version(pid, result.ruleset_version)


def _key_of(spec: dict | None, letter: str, field: str) -> str | None:
    """The stored key behind BidResult.fields[letter][field]: through the item's form."""
    if not spec:
        return None
    item = next((i for i in RuleSet.model_validate(spec).items if i.letter == letter), None)
    form = form_for(item) if item is not None else None
    return form.key(field) if form is not None else None


@router.patch("/projects/{pid}/bids/{tenderer}/fields/{letter}/{field}")
def correct_field(pid: str, tenderer: str, letter: str, field: str, body: CorrectionRequest,
                  user: str = Depends(deps.acting_user)) -> BidResult:
    """Correct a value, mark a document present or absent, or point at another page. The
    model's value is kept beside the person's; the engine re-decides at once, no model
    call; a review confirmation on this tenderer is withdrawn."""
    pdir = deps._project_dir(pid)
    runner = deps.runner()
    run, result, spec = _checked(runner, pid, tenderer)
    key = _key_of(spec, letter, field)
    # A field a reviewer enters may be missing from a result stored before it existed; it is
    # the item's form's field all the same, and entering it needs no new reading.
    if key is None or (key not in result.fields and not by_reviewer(key)):
        raise ApiError(404, "not_found", f"item ({letter}) has no field {field!r} in {tenderer}'s result")
    entries = correction_entries(result.fields, key, body.value, body.present, body.page)
    if not entries:
        raise ApiError(400, "bad_request", "the correction changes nothing: give a value, present or a page")

    def outcome(verdict: dict) -> str | None:
        return (item_verdicts(verdict).get(letter) or verdict).get("outcome")

    before = {"fields": {k: result.fields.get(k) for k in entries}, "verdict": outcome(result.verdict)}
    corrected = runner.correct_fields(run["run_id"], entries, body.reason, user)
    after = {"fields": entries, "verdict": outcome(corrected.verdict)}
    runner.store.event("result.corrected", pid, f"{tenderer}:{letter}.{field}", before, after, user, body.reason)
    return _bid_result(pid, pdir, run, corrected, runner.store.steps(run["run_id"]), spec)


@router.post("/projects/{pid}/bids/{tenderer}/review/confirm")
def confirm_review(pid: str, tenderer: str, user: str = Depends(deps.acting_user)) -> BidResult:
    """409 while any checked field still needs review; reports wait for this."""
    pdir = deps._project_dir(pid)
    runner = deps.runner()
    run, result, spec = _checked(runner, pid, tenderer)
    still_open = open_reviews(result.verdict)
    if still_open:
        raise ApiError(409, "conflict", f"{len(still_open)} field(s) still need review", {"fields": still_open})
    confirmed = runner.confirm_review(run["run_id"], user)
    runner.store.event("review.confirmed", pid, tenderer, None, {"ruleset_version": confirmed.ruleset_version}, user)
    return _bid_result(pid, pdir, run, confirmed, runner.store.steps(run["run_id"]), spec)


@router.post("/projects/{pid}/evaluate", status_code=202)
def evaluate(pid: str, body: EvaluateRequest | None = None, user: str = Depends(deps.acting_user)) -> JobStarted:
    """Every checked tenderer re-decided against a confirmed rule-set version, as a job.
    Engine only: no model call. Results are pinned to the version; a result whose
    verdict changed loses its review confirmation."""
    deps._project_dir(pid)
    runner = deps.runner()
    store = runner.store
    version = body.version if body and body.version else None
    if version is None:
        latest = store.latest_confirmed(pid)
        if latest is None:
            raise ApiError(409, "unconfirmed_ruleset", f"project {pid} has no confirmed rule set")
        version = latest[0]
    spec = store.get_version(pid, version)
    if spec is None or spec.get("status") != "confirmed":
        raise ApiError(404, "not_found", f"rule set version {version} of {pid} is not a confirmed version")
    active = store.active_run(pid, EVALUATE)
    if active:
        raise ApiError(409, "conflict", "an evaluation is already running", {"job_id": active})
    job_id = runner.start(pid, EVALUATE, "evaluate", data={"version": version})
    store.event("evaluate.started", pid, f"v{version}", None, {"job_id": job_id}, user)
    return JobStarted(job_id=job_id)


@router.post("/projects/{pid}/jobs/{job_id}/retry", status_code=202)
def retry_job(pid: str, job_id: str, user: str = Depends(deps.acting_user)) -> JobStarted:
    """A failed or dead job continues from its saved steps."""
    deps._project_dir(pid)
    runner = deps.runner()
    try:
        run = runner.store.run(job_id)
    except KeyError:
        raise ApiError(404, "not_found", f"no job {job_id}")
    if run["project"] != pid:
        raise ApiError(404, "not_found", f"no job {job_id} in {pid}")
    try:
        runner.retry(job_id)
    except ValueError as err:
        raise ApiError(409, "conflict", str(err))
    runner.store.event("job.retried", pid, run["tenderer"], {"state": run["state"], "error": run["error"]}, None, user)
    return JobStarted(job_id=job_id)

"""Rule sets: the draft, its confirmation, the versions, and the S3 editing routes for
items, notes, gaps and diffs. Every edit goes to the open draft (opened from the latest
confirmed version when there is none), is validated against app/rulesets/schema.py,
saved with the person as `updated_by`, and written as an event with their reason."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from pydantic import ValidationError

from app.rulesets import edit as ed
from app.rulesets.library import load_templates
from app.jobs.models import TENDER
from app.rulesets.schema import Gap, RuleSet, RuleSetItem
from backend import deps
from backend.errors import ApiError
from backend.schemas_api import BuildResponse, Diff, ItemPatch, NewItem, NotePatch, ReasonBody, RuleSetVersion
from backend.times import when

router = APIRouter(dependencies=[Depends(deps.require_key)])
_when = when   # the unit tests know it by this name


def _ruleset(store, pid: str, spec: dict) -> RuleSet:
    """The stored spec as the shared model, with the server-owned `updated_by` filled in."""
    return RuleSet.model_validate({**spec, "updated_by": store.editor_of(pid, spec.get("version"))})


def _current(store, pid: str) -> dict:
    """The draft, else the latest confirmed version."""
    draft = store.draft(pid)
    if draft:
        return draft[1]
    confirmed = store.latest_confirmed(pid)
    if confirmed:
        return confirmed[1]
    raise ApiError(404, "not_found", f"project {pid} has no rule set yet; PUT /projects/{pid}/ruleset/draft")


def _errors(err: ValidationError) -> dict:
    return {"errors": err.errors(include_url=False, include_context=False, include_input=False)}


def _now() -> datetime:
    return datetime.now(timezone.utc)
def _when(value) -> datetime | None:
    """Epoch seconds (float, or Decimal from psycopg) or an already-built datetime, as ISO."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


@router.get("/projects/{pid}/ruleset")
def get_ruleset(pid: str, version: int | None = None) -> RuleSet:
    deps._project_dir(pid)
    store = deps.runner().store
    if version is not None:
        spec = store.get_version(pid, version)
        if spec is None:
            raise ApiError(404, "not_found", f"rule set version {version} does not exist for {pid}")
        return _ruleset(store, pid, spec)
    return _ruleset(store, pid, _current(store, pid))


@router.get("/projects/{pid}/ruleset/versions")
def list_versions(pid: str) -> list[RuleSetVersion]:
    deps._project_dir(pid)
    return [RuleSetVersion(**{**v, "created_at": when(v["created_at"]), "confirmed_at": when(v["confirmed_at"])})
            for v in deps.runner().store.versions(pid)]


@router.put("/projects/{pid}/ruleset/draft")
def put_draft(pid: str, body: dict, user: str = Depends(deps.acting_user)) -> RuleSet:
    """The whole draft as JSON, validated against app/rulesets/schema.py. The server owns
    version, status and the audit fields."""
    deps._project_dir(pid)
    store = deps.runner().store
    candidate = {**body, "project_id": pid, "version": body.get("version") or 1, "status": "draft",
                 "confirmed_by": None, "confirmed_at": None, "updated_by": None}
    candidate.setdefault("created_by", user)
    try:
        ruleset = RuleSet.model_validate(candidate)
    except ValidationError as err:
        raise ApiError(422, "validation_failed", "the rule set does not validate", _errors(err))
    spec = ruleset.model_dump(mode="json")
    before = store.draft(pid)
    version, created = store.save_draft(pid, spec, user)
    spec = store.get_version(pid, version)
    store.event("ruleset.draft_saved", pid, f"v{version}", before[1] if before else None, spec, user,
                "new draft" if created else "draft replaced")
    return _ruleset(store, pid, spec)


@router.post("/projects/{pid}/ruleset/confirm")
def confirm(pid: str, user: str = Depends(deps.acting_user)) -> RuleSet:
    """403 self_approval if the approver last edited the draft; 409 conflict with
    `details.blockers` while an item needs input, a required slot of its template is
    empty whatever the item's status (I1.15), or a gap has no reason. Confirms the draft
    as version N."""
    deps._project_dir(pid)
    store = deps.runner().store
    draft = store.draft(pid)
    if draft is None:
        raise ApiError(409, "conflict", f"project {pid} has no draft to confirm")
    version, spec = draft
    editor = store.editor_of(pid, version)
    if editor and editor == user:
        raise ApiError(403, "self_approval", f"{user} last edited draft v{version}; another person must confirm it")
    blockers = ed.confirm_blockers(RuleSet.model_validate(spec), load_templates())
    if blockers:
        raise ApiError(409, "conflict", "the draft cannot be confirmed yet: " + "; ".join(ed.describe_blocker(b) for b in blockers),
                       {"blockers": blockers})
    try:
        RuleSet.model_validate({**spec, "status": "confirmed", "confirmed_by": user,
                                "confirmed_at": "2000-01-01T00:00:00Z"})
    except ValidationError as err:
        raise ApiError(409, "conflict", "the draft cannot be confirmed yet", _errors(err))
    confirmed_version = store.confirm(pid, user)
    deps.runner().resume_paused(pid)                     # runs waiting for this rule set continue at once
    after = store.get_version(pid, confirmed_version)
    store.event("ruleset.confirmed", pid, f"v{confirmed_version}", spec, after, user)
    return _ruleset(store, pid, after)


# ---------------------------------------------------------------- editing (S3)

def _open_draft(store, pid: str, user: str) -> tuple[int, RuleSet]:
    """The draft to edit: the open one, or a new one opened from the latest confirmed
    version (draft N+1 whose parent is N)."""
    draft = store.draft(pid)
    if draft is None:
        confirmed = store.latest_confirmed(pid)
        if confirmed is None:
            raise ApiError(404, "not_found", f"project {pid} has no rule set yet; PUT /projects/{pid}/ruleset/draft")
        base = {**confirmed[1], "status": "draft", "confirmed_by": None, "confirmed_at": None, "updated_by": None}
        version, _ = store.save_draft(pid, base, user)
        draft = (version, store.get_version(pid, version))
        store.event("ruleset.draft_opened", pid, f"v{version}", None, draft[1], user, f"edit of confirmed v{confirmed[0]}")
    version, spec = draft
    return version, RuleSet.model_validate(spec)


def _save(store, pid: str, version: int, ruleset: RuleSet, user: str, kind: str, subject: str,
          before, after, reason: str) -> RuleSet:
    """Validate the edited rule set whole (model_copy does not), replace the draft, log."""
    try:
        spec = RuleSet.model_validate(ruleset.model_dump(mode="json")).model_dump(mode="json")
    except ValidationError as err:
        raise ApiError(422, "validation_failed", "the edit leaves the rule set invalid", _errors(err))
    spec["version"] = version
    store.save_draft(pid, spec, user)
    store.event(kind, pid, subject, before, after, user, reason)
    return _ruleset(store, pid, store.get_version(pid, version))


def _edit_error(err: ed.EditError) -> ApiError:
    return ApiError(404 if err.code == "not_found" else 400, err.code, err.message)


def _dump(model) -> dict | None:
    return model.model_dump(mode="json") if model is not None else None


@router.patch("/projects/{pid}/ruleset/items/{letter}")
def patch_item(pid: str, letter: str, body: ItemPatch, user: str = Depends(deps.acting_user)) -> RuleSetItem:
    """A slot value, a rule, the template or a note; `reason` required. The item becomes
    `edited`; a corrected slot keeps the model's value beside the person's."""
    deps._project_dir(pid)
    store = deps.runner().store
    version, ruleset = _open_draft(store, pid, user)
    try:
        before = ed.find_item(ruleset, letter)
        after = ed.apply_patch(before, body, user, _now(), load_templates())
    except ed.EditError as err:
        raise _edit_error(err)
    saved = _save(store, pid, version, ed.replace_item(ruleset, after), user, "ruleset.item_patched",
                  f"v{version}:{letter}", _dump(before), _dump(after), body.reason)
    return ed.find_item(saved, letter)


@router.post("/projects/{pid}/ruleset/items", status_code=201)
def add_item(pid: str, body: NewItem, user: str = Depends(deps.acting_user)) -> RuleSetItem:
    """An item a person adds from a clause: lettered x1, x2, ...; `edited` with their record."""
    deps._project_dir(pid)
    store = deps.runner().store
    version, ruleset = _open_draft(store, pid, user)
    try:
        item = ed.add_item(ruleset, body, user, _now())
    except ValidationError as err:
        raise ApiError(422, "validation_failed", "the new item does not validate", _errors(err))
    saved = _save(store, pid, version, ruleset.model_copy(update={"items": [*ruleset.items, item]}), user,
                  "ruleset.item_added", f"v{version}:{item.letter}", None, _dump(item), body.reason)
    return ed.find_item(saved, item.letter)


@router.delete("/projects/{pid}/ruleset/items/{letter}", status_code=204)
def delete_item(pid: str, letter: str, body: ReasonBody, user: str = Depends(deps.acting_user)) -> Response:
    deps._project_dir(pid)
    store = deps.runner().store
    version, ruleset = _open_draft(store, pid, user)
    try:
        before = ed.find_item(ruleset, letter)
        after = ed.remove_item(ruleset, letter)
    except ed.EditError as err:
        raise _edit_error(err)
    _save(store, pid, version, after, user, "ruleset.item_removed", f"v{version}:{letter}", _dump(before), None, body.reason)
    return Response(status_code=204)


@router.patch("/projects/{pid}/ruleset/items/{letter}/notes/{index}")
def patch_note(pid: str, letter: str, index: int, body: NotePatch, user: str = Depends(deps.acting_user)) -> RuleSetItem:
    deps._project_dir(pid)
    store = deps.runner().store
    version, ruleset = _open_draft(store, pid, user)
    try:
        before = ed.find_item(ruleset, letter)
        after = ed.edit_note(before, index, body.note, user, _now(), body.reason)
    except ed.EditError as err:
        raise _edit_error(err)
    saved = _save(store, pid, version, ed.replace_item(ruleset, after), user, "ruleset.note_edited",
                  f"v{version}:{letter}:notes/{index}", _dump(before), _dump(after), body.reason)
    return ed.find_item(saved, letter)


@router.delete("/projects/{pid}/ruleset/items/{letter}/notes/{index}")
def delete_note(pid: str, letter: str, index: int, body: ReasonBody, user: str = Depends(deps.acting_user)) -> RuleSetItem:
    deps._project_dir(pid)
    store = deps.runner().store
    version, ruleset = _open_draft(store, pid, user)
    try:
        before = ed.find_item(ruleset, letter)
        after = ed.remove_note(before, index, user, _now(), body.reason)
    except ed.EditError as err:
        raise _edit_error(err)
    saved = _save(store, pid, version, ed.replace_item(ruleset, after), user, "ruleset.note_removed",
                  f"v{version}:{letter}:notes/{index}", _dump(before), _dump(after), body.reason)
    return ed.find_item(saved, letter)


@router.get("/projects/{pid}/ruleset/gaps")
def list_gaps(pid: str) -> list[Gap]:
    """The current rule set's gaps: clauses no rule covers, with reasons once given."""
    deps._project_dir(pid)
    store = deps.runner().store
    return _ruleset(store, pid, _current(store, pid)).gaps


@router.patch("/projects/{pid}/ruleset/gaps/{node_id:path}")
def patch_gap(pid: str, node_id: str, body: ReasonBody, user: str = Depends(deps.acting_user)) -> Gap:
    """Why a gap is acceptable, recorded as `Gap.edit` (I1.12)."""
    deps._project_dir(pid)
    store = deps.runner().store
    version, ruleset = _open_draft(store, pid, user)
    try:
        before = next((g for g in ruleset.gaps if g.node_id == node_id), None)
        after, gap = ed.set_gap_reason(ruleset, node_id, body.reason, user, _now())
    except ed.EditError as err:
        raise _edit_error(err)
    saved = _save(store, pid, version, after, user, "ruleset.gap_reasoned", f"v{version}:gap:{node_id}",
                  _dump(before), _dump(gap), body.reason)
    return next(g for g in saved.gaps if g.node_id == node_id)


@router.get("/projects/{pid}/ruleset/diff")
def get_diff(pid: str, from_version: int = Query(alias="from"), to: int = Query()) -> Diff:
    """Items added, removed and changed between two versions; a change a person made
    carries their edit record, one the rule builder made carries none."""
    deps._project_dir(pid)
    store = deps.runner().store
    specs = {}
    for version in (from_version, to):
        spec = store.get_version(pid, version)
        if spec is None:
            raise ApiError(404, "not_found", f"rule set version {version} does not exist for {pid}")
        specs[version] = RuleSet.model_validate(spec)
    return Diff.model_validate(ed.diff(specs[from_version], specs[to]))


# ---------------------------------------------------------------- the rule builder (S3)

@router.post("/projects/{pid}/ruleset/build", status_code=202)
def build(pid: str, user: str = Depends(deps.acting_user)) -> BuildResponse:
    """L0 to L4 on the tender's documents, as a job on the worker. The result is the draft
    (a new one, or the open one replaced), never overwriting a person's edits: an edited
    item keeps its version and a corrected slot gets the new suggestion as `model_value`.
    409 while a build is running or when the project has no tender documents."""
    pdir = deps._project_dir(pid)
    if not any((pdir / "tender").glob("*.pdf")):
        raise ApiError(409, "conflict", f"project {pid} has no tender documents to build from")
    runner = deps.runner()
    active = runner.store.active_run(pid, TENDER)
    if active:
        raise ApiError(409, "conflict", "a rule-set build is already running", {"job_id": active})
    job_id = runner.start(pid, TENDER, "ruleset_build")
    runner.store.event("ruleset.build_started", pid, None, None, {"job_id": job_id}, user)
    return BuildResponse(job_id=job_id)

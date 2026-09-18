"""Rule sets: the draft, its confirmation, the versions. The whole-draft editor is enough
for S2 (a check needs a confirmed rule set); item-level edits, diffs and gaps come with
the rule builder at S3."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import ValidationError

from app.rulesets.schema import RuleSet
from backend import deps
from backend.errors import ApiError
from backend.schemas_api import RuleSetVersion

router = APIRouter(dependencies=[Depends(deps.require_key)])


@router.get("/projects/{pid}/ruleset")
def get_ruleset(pid: str, version: int | None = None) -> dict:
    deps._project_dir(pid)
    store = deps.runner().store
    if version is not None:
        spec = store.get_version(pid, version)
        if spec is None:
            raise ApiError(404, "not_found", f"rule set version {version} does not exist for {pid}")
        return spec
    draft = store.draft(pid)
    if draft:
        return draft[1]
    confirmed = store.latest_confirmed(pid)
    if confirmed:
        return confirmed[1]
    raise ApiError(404, "not_found", f"project {pid} has no rule set yet; PUT /projects/{pid}/ruleset/draft")


@router.get("/projects/{pid}/ruleset/versions")
def list_versions(pid: str) -> list[RuleSetVersion]:
    deps._project_dir(pid)
    return [RuleSetVersion(**v) for v in deps.runner().store.versions(pid)]


@router.put("/projects/{pid}/ruleset/draft")
def put_draft(pid: str, body: dict, user: str = Depends(deps.acting_user)) -> dict:
    """The whole draft as JSON, validated against app/rulesets/schema.py. The server owns
    version, status and the audit fields."""
    deps._project_dir(pid)
    store = deps.runner().store
    candidate = {**body, "project_id": pid, "version": body.get("version") or 1, "status": "draft",
                 "confirmed_by": None, "confirmed_at": None}
    candidate.setdefault("created_by", user)
    try:
        ruleset = RuleSet.model_validate(candidate)
    except ValidationError as err:
        raise ApiError(422, "validation_failed", "the rule set does not validate", {"errors": err.errors(include_url=False, include_context=False, include_input=False)})
    spec = ruleset.model_dump(mode="json")
    before = store.draft(pid)
    version, created = store.save_draft(pid, spec, user)
    spec = store.get_version(pid, version)
    store.event("ruleset.draft_saved", pid, f"v{version}", before[1] if before else None, spec, user,
                "new draft" if created else "draft replaced")
    return spec


@router.post("/projects/{pid}/ruleset/confirm")
def confirm(pid: str, user: str = Depends(deps.acting_user)) -> dict:
    """403 self_approval if the approver last edited the draft; 409 conflict while an
    item still needs input or a gap has no reason. Confirms the draft as version N."""
    deps._project_dir(pid)
    store = deps.runner().store
    draft = store.draft(pid)
    if draft is None:
        raise ApiError(409, "conflict", f"project {pid} has no draft to confirm")
    version, spec = draft
    editor = next((v["updated_by"] for v in store.versions(pid) if v["version"] == version), None)
    if editor and editor == user:
        raise ApiError(403, "self_approval", f"{user} last edited draft v{version}; another person must confirm it")
    try:
        RuleSet.model_validate({**spec, "status": "confirmed", "confirmed_by": user,
                                "confirmed_at": "2000-01-01T00:00:00Z"})
    except ValidationError as err:
        raise ApiError(409, "conflict", "the draft cannot be confirmed yet", {"errors": err.errors(include_url=False, include_context=False, include_input=False)})
    confirmed_version = store.confirm(pid, user)
    deps.runner().resume_paused(pid)                     # runs waiting for this rule set continue at once
    after = store.get_version(pid, confirmed_version)
    store.event("ruleset.confirmed", pid, f"v{confirmed_version}", spec, after, user)
    return after

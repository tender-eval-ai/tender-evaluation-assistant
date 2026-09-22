"""The S4-4 routes: the price summary and the evaluation across tenderers from the
confirmed rule set and the checked results, and the Word reports, which refuse until every
checked tenderer's review is confirmed."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.checks import pricing, reports
from app.config import Config
from app.jobs.store import _apply
from app.rulesets.schema import RuleSet
from backend import deps
from backend.errors import ApiError
from backend.schemas_api import Evaluation, PriceSummary, ReportInfo

router = APIRouter(dependencies=[Depends(deps.require_key)])


def _version(store, pid: str, version: int | None) -> int:
    if version is not None:
        spec = store.get_version(pid, version)
        if spec is None or spec.get("status") != "confirmed":
            raise ApiError(404, "not_found", f"rule set version {version} of {pid} is not a confirmed version")
        return version
    latest = store.latest_confirmed(pid)
    if latest is None:
        raise ApiError(409, "unconfirmed_ruleset", f"project {pid} has no confirmed rule set")
    return latest[0]


def _offers(pid: str, version: int | None):
    """The confirmed rule set and every checked tenderer's result at that version, with the
    reviewer's corrections applied; the tenderers checked against another version."""
    store = deps.runner().store
    version = _version(store, pid, version)
    ruleset = RuleSet.model_validate(store.get_version(pid, version))
    offers, missing = [], []
    for r in store.project_results(pid):
        if r.ruleset_version != version:
            missing.append(r.tenderer)
            continue
        offers.append(pricing.Offer(tenderer=r.tenderer, run_id=r.run_id, fields=_apply(r.fields, r.corrections), verdict=r.verdict,
                                    reviewed_by=r.review_confirmed_by, corrections=r.corrections))
    return ruleset, offers, missing


@router.get("/projects/{pid}/price-summary")
def price_summary(pid: str, version: int | None = None) -> PriceSummary:
    deps._project_dir(pid)
    ruleset, offers, missing = _offers(pid, version)
    return PriceSummary.model_validate(pricing.price_summary(ruleset, offers, missing))


@router.get("/projects/{pid}/evaluation")
def evaluation(pid: str, version: int | None = None) -> Evaluation:
    deps._project_dir(pid)
    ruleset, offers, missing = _offers(pid, version)
    return Evaluation.model_validate(pricing.evaluation(ruleset, offers, missing))


def _reports_dir(pdir, version: int):
    return pdir / "work" / "reports" / f"v{version}"


@router.get("/projects/{pid}/reports")
def list_reports(pid: str, version: int | None = None) -> list[ReportInfo]:
    pdir = deps._project_dir(pid)
    ruleset, offers, _ = _offers(pid, version)
    approver = ", ".join(sorted({o.reviewed_by for o in offers if o.reviewed_by})) or None
    out = []
    for name in reports.NAMES:
        path = _reports_dir(pdir, ruleset.version) / name
        when = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) if path.is_file() else None
        out.append(ReportInfo(name=name, version=ruleset.version, generated_at=when, approver=approver))
    return out


@router.get("/projects/{pid}/reports/{name}")
def download_report(pid: str, name: str, version: int | None = None) -> Response:
    """Rendered fresh from the stored results; `409 review_pending` while a checked
    tenderer's review is not confirmed, so no report goes out on an unreviewed verdict."""
    pdir = deps._project_dir(pid)
    if name not in reports.NAMES:
        raise ApiError(404, "not_found", f"no report {name!r}; the reports are {', '.join(reports.NAMES)}")
    ruleset, offers, _ = _offers(pid, version)
    if not offers:
        raise ApiError(404, "not_found", "no checked tenderer at this rule-set version")
    pending = sorted(o.tenderer for o in offers if not o.reviewed_by)
    if pending:
        raise ApiError(409, "review_pending", f"the review of {', '.join(pending)} is not confirmed", {"tenderers": pending})
    meta = deps._read_json(pdir / "meta.json") if (pdir / "meta.json").is_file() else {}
    cfg = Config()
    bundle = reports.Bundle(project=meta.get("name") or pid, ruleset=ruleset, offers=offers,
                            evaluation=pricing.evaluation(ruleset, offers), models={"text": cfg.text_model, "vision": cfg.vision_model})
    data = reports.render(name, bundle)
    folder = _reports_dir(pdir, ruleset.version)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    return Response(content=data, media_type=deps.DOCX_MIME, headers={"Content-Disposition": f'attachment; filename="{name}"'})

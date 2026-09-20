"""docs/openapi.json is the API contract's snapshot: an accidental route or model
change fails here. Review docs/api_contract.md first, then regenerate:

    UPDATE_OPENAPI=1 python -m pytest test/test_api_contract.py
"""
import importlib
import json
import os
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"


def current(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("API_KEY", raising=False)
    import backend.api as api
    importlib.reload(api)
    return json.dumps(api.app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def test_the_openapi_snapshot_matches_the_app(tmp_path, monkeypatch):
    now = current(tmp_path, monkeypatch)
    if os.environ.get("UPDATE_OPENAPI"):
        SNAPSHOT.write_text(now)
    assert SNAPSHOT.is_file(), "no snapshot yet: UPDATE_OPENAPI=1 python -m pytest test/test_api_contract.py"
    assert SNAPSHOT.read_text() == now, ("the API changed: update docs/api_contract.md (a `contract` PR, both approvals), "
                                         "then UPDATE_OPENAPI=1 python -m pytest test/test_api_contract.py")


def test_the_s2_routes_are_in_the_snapshot():
    spec = json.loads(SNAPSHOT.read_text())
    for path in ["/projects/{pid}/checks", "/projects/{pid}/jobs", "/projects/{pid}/jobs/{job_id}",
                 "/projects/{pid}/bids/{tenderer}/results", "/projects/{pid}/ruleset", "/projects/{pid}/ruleset/draft",
                 "/projects/{pid}/ruleset/confirm", "/projects/{pid}/ruleset/versions", "/projects/{pid}/documents",
                 "/projects/{pid}/documents/{doc_id}/pages", "/projects/{pid}/documents/{doc_id}/pages/{n}/image",
                 "/projects/{pid}/events"]:
        assert path in spec["paths"], path
    assert {"BidResult", "Job", "Verdict", "PageCitation", "Document", "Page", "Event", "Project", "Progress",
            "RuleSet", "RuleSetItem", "PartSpec", "RuleSetVersion", "ErrorBody"} <= set(spec["components"]["schemas"])


def test_errors_are_the_envelope_in_the_snapshot_too():
    """Checklist I1.9: a 422 is ErrorBody, not FastAPI's HTTPValidationError."""
    spec = json.loads(SNAPSHOT.read_text())
    assert "HTTPValidationError" not in spec["components"]["schemas"]
    put = spec["paths"]["/projects/{pid}/ruleset/draft"]["put"]["responses"]
    assert put["422"]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorBody")
    assert put["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/RuleSet")

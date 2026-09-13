"""Streamlit UI smoke tests (streamlit.testing.v1.AppTest) against the real backend
served in-process through FastAPI's TestClient — no sockets, no models."""
import importlib

import pytest
import requests
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from test.conftest import FIXTURES, ROOT

UI = ROOT / "frontend" / "ui.py"


@pytest.fixture
def backend(tmp_path, monkeypatch):
    """The API app on a temp data dir, with `requests.request` (the UI's only HTTP
    path) rerouted into it."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("INBOX_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("GITHUB_MODELS_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("BACKEND_URL", "http://backend.test")
    import backend.api as api
    importlib.reload(api)
    client = TestClient(api.app)

    def shim(method, url, headers=None, timeout=None, **kwargs):
        return client.request(method, url.replace("http://backend.test", ""), headers=headers, **kwargs)

    monkeypatch.setattr(requests, "request", shim)
    monkeypatch.setattr(requests, "get", lambda url, **kw: shim("GET", url, **kw))
    return api, client


def _project_with_rubric(client) -> str:
    pid = client.post("/projects", json={"name": "ui test", "synthetic": True}).json()["id"]
    client.put(f"/projects/{pid}/rubric", json=__import__("json").loads((FIXTURES / "rubric.json").read_text()))
    client.post(f"/projects/{pid}/bids/Bidder A", files=[("files", ("offer.pdf", b"%PDF-1.4 stub", "application/pdf"))])
    return pid


def _open_extraction_page(pid: str) -> AppTest:
    """Launch the app, pick the project in the sidebar (labels are "name (id)"),
    switch to the Extraction page."""
    at = AppTest.from_file(str(UI), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    at.selectbox[0].select(f"ui test ({pid})").run()
    at.session_state["nav_v2"] = "3 · Extraction (review)"
    at.run()
    assert not at.exception, at.exception
    return at


def test_run_button_follows_an_already_running_job_instead_of_crashing(backend):
    """The exact failure a user hit: a job started elsewhere is still running, the
    Extraction page still offered 'Run', the backend answered 409 and the page died
    with a traceback. Now the page follows the job."""
    api, client = backend
    pid = _project_with_rubric(client)
    at = _open_extraction_page(pid)
    run_buttons = [b for b in at.button if "Run extraction" in b.label]
    assert run_buttons, [b.label for b in at.button]
    # Backend thinks a job is running (in-process guard), status file says paused.
    api._running.add(pid)
    try:
        run_buttons[0].click().run()
    finally:
        api._running.discard(pid)
    assert not at.exception, at.exception
    assert any("already running" in str(el.value).lower() for el in at.info), [str(i.value) for i in at.info]


def test_pages_follow_a_running_job_rather_than_offering_a_start(backend, monkeypatch):
    """With a job running, the Extraction page must attach to it (no start button).
    The fake job ends — in an error, so the page keeps the "following" message and
    the error on screen instead of rerunning — on the page's second read of the
    status endpoint: the first is the attach check, the second the poll loop's."""
    import sys
    api, client = backend
    pid = _project_with_rubric(client)
    api._set_status(api.PROJECTS / pid, "running", "extracting Bidder A")
    reads = {"status_endpoint": 0}
    real_get_status = api._get_status

    def ends_on_second_poll(pdir):
        if sys._getframe(1).f_code.co_name == "status":      # only GET …/status reads
            reads["status_endpoint"] += 1
            if reads["status_endpoint"] >= 2:
                api._set_status(pdir, "error", "ValueError: boom")
        return real_get_status(pdir)

    monkeypatch.setattr(api, "_get_status", ends_on_second_poll)
    at = _open_extraction_page(pid)
    assert reads["status_endpoint"] >= 2, "the page never polled the running job"
    assert not [b for b in at.button if "Run extraction" in b.label], "a start button was offered while a job ran"
    assert any("already running" in str(el.value).lower() for el in at.info), [str(i.value) for i in at.info]
    assert any("boom" in str(el.value) for el in at.error), [str(e.value) for e in at.error]

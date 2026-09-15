"""MCP surface (mcp_server/): read-only tools over a project's documents, on-demand
OCR with a budget and a shared cache, the synthetic-only confidentiality guard, the
API-key-guarded HTTP transport, and the local-model client answering a scripted
question only with a quote it can verify — all offline."""
import asyncio
import io
import json
import shutil
import socket
import threading
import time
import urllib.request
from urllib.error import HTTPError

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.config import Config
from mcp_server.local_client import (ClientAction, answer_question, build_llm,
                                     is_local_endpoint, server_params)
from mcp_server.server import Policy, build_http_app, build_server
from test.fakes import FakeLLM, Rule
from test.conftest import FIXTURES
from tools.pdfgen import make_text_pdf

PAGE1 = ("Offer of Tenderer X - Tender Ref. DEMO0022026\n"
         "Table of Contents: page 2 Certificates and Declarations; page 3 Price Schedule.\n"
         "Delivery within 30 days from the purchase order is confirmed.")
CERT_OCR = "Non-collusive Tendering Certificate: completed and signed by the director."
TERMS = "Terms of Tender. Delivery within 45 days is an essential requirement. " * 3
TOOLS = {"list_projects", "list_bids", "get_rubric", "select_tender", "select_bid",
         "list_pages", "search_pages", "read_page", "ocr_page"}


def _jpeg() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (24, 24), "white").save(buf, format="JPEG")
    return buf.getvalue()


def make_project(root, pid, synthetic, with_rubric=False):
    """Backend layout: page 1 of the offer has a text layer, pages 2-3 are scans."""
    pdir = root / "projects" / pid
    (pdir / "bids" / "Tenderer_X").mkdir(parents=True)
    (pdir / "tender").mkdir()
    (pdir / "work").mkdir()
    meta = {"id": pid, "name": f"Project {pid}", "created": 0}
    if synthetic is not None:
        meta["synthetic"] = synthetic
    (pdir / "meta.json").write_text(json.dumps(meta))
    make_text_pdf(pdir / "bids" / "Tenderer_X" / "offer.pdf",
                  PAGE1.splitlines() + [""] * 45 + [""] * 48 + [""],
                  images={1: _jpeg(), 2: _jpeg()})
    make_text_pdf(pdir / "tender" / "terms.pdf", TERMS)
    if with_rubric:
        shutil.copy(FIXTURES / "rubric.json", pdir / "work" / "rubric.json")
    return pdir


class OCRStub:
    def __init__(self, text=CERT_OCR):
        self.calls, self.text = 0, text

    def ocr_page(self, png_bytes):
        self.calls += 1
        return self.text


def make_server(root, transport="stdio", local_model=False, ocr_budget=1):
    ocr = OCRStub()

    def cfg_factory(pdir):
        cfg = Config()
        cfg.cache_dir = pdir / "work" / "cache"
        cfg.agent_ocr_pages = ocr_budget
        return cfg

    server = build_server(root, Policy(transport=transport, local_model=local_model),
                          cfg_factory=cfg_factory, llm_factory=lambda cfg: ocr)
    return server, ocr


async def call(client, tool, args=None):
    r = await client.call_tool(tool, args or {})
    return "\n".join(c.text for c in r.content), bool(r.is_error)


def _files(root):
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


# ---------------------------------------------------------------- tools

def test_tools_are_listed_and_all_read_only(tmp_path):
    server, _ = make_server(tmp_path)

    async def run():
        async with Client(server) as c:
            return (await c.list_tools()).tools

    tools = asyncio.run(run())
    assert {t.name for t in tools} == TOOLS
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)
    schema = next(t for t in tools if t.name == "select_bid").input_schema
    assert set(schema["required"]) == {"project", "tenderer"}     # ctx is not exposed


def test_walk_offer_with_on_demand_ocr_budget_and_cache(tmp_path):
    pdir = make_project(tmp_path, "demo-1", synthetic=True, with_rubric=True)
    server, ocr = make_server(tmp_path, ocr_budget=1)
    before = _files(tmp_path)

    async def run():
        async with Client(server) as c:
            out = {}
            out["projects"], _ = await call(c, "list_projects")
            out["bids"], _ = await call(c, "list_bids", {"project": "demo-1"})
            out["rubric"], _ = await call(c, "get_rubric", {"project": "demo-1"})
            out["unselected"], out["unselected_err"] = await call(c, "list_pages")
            out["select"], _ = await call(c, "select_bid", {"project": "demo-1", "tenderer": "Tenderer_X"})
            out["search0"], _ = await call(c, "search_pages", {"query": "Non-collusive"})
            out["read2"], _ = await call(c, "read_page", {"page": 2})
            out["ocr2"], _ = await call(c, "ocr_page", {"page": 2})
            out["search1"], _ = await call(c, "search_pages", {"query": "Non-collusive"})
            out["ocr3"], _ = await call(c, "ocr_page", {"page": 3})
            out["read1"], _ = await call(c, "read_page", {"page": 1})
            out["bad"], out["bad_err"] = await call(c, "read_page", {"page": 9})
            out["tender"], _ = await call(c, "select_tender", {"project": "demo-1"})
            out["terms"], _ = await call(c, "read_page", {"page": 1})
        # A new connection: the cached transcription is picked up without OCR.
        async with Client(server) as c:
            out["select_again"], _ = await call(c, "select_bid", {"project": "demo-1", "tenderer": "Tenderer_X"})
            out["read2_again"], _ = await call(c, "read_page", {"page": 2})
        return out

    out = asyncio.run(run())
    assert "demo-1 — Project demo-1 [synthetic] — tenderers: Tenderer_X" in out["projects"]
    assert "Tenderer_X: offer.pdf (3 pages)" in out["bids"] and "terms.pdf" in out["bids"]
    assert "S1-" in out["rubric"] and "Stage II" in out["rubric"]
    assert out["unselected_err"] and "select_bid" in out["unselected"]
    assert "2 scanned page(s) are [skipped]" in out["select"]
    assert "offer.pdf p.2 [skipped]" in out["select"] and "offer.pdf p.1 [text]" in out["select"]
    assert "no page read so far" in out["search0"]
    assert "has not been read" in out["read2"] and "ocr_page(2)" in out["read2"]
    assert out["ocr2"] == CERT_OCR and ocr.calls == 1
    assert "offer.pdf p.2" in out["search1"]
    assert "OCR budget exhausted" in out["ocr3"] and ocr.calls == 1
    assert "Table of Contents" in out["read1"]
    assert out["bad_err"] and "pages 1..3" in out["bad"]
    assert "Selected tender of project demo-1" in out["tender"]
    assert "Delivery within 45 days" in out["terms"]
    assert "offer.pdf p.2 [ocr]" in out["select_again"] and out["read2_again"] == CERT_OCR
    assert ocr.calls == 1
    # Nothing written except the OCR cache the pipeline shares.
    new = _files(tmp_path) - before
    assert new and all(f.startswith("projects/demo-1/work/cache/") for f in new), new
    assert (pdir / "meta.json").read_text() == json.dumps({"id": "demo-1", "name": "Project demo-1",
                                                           "created": 0, "synthetic": True})


# ---------------------------------------------------------------- confidentiality guard

def test_unflagged_projects_are_withheld_unless_local_model_client(tmp_path):
    make_project(tmp_path, "real-1", synthetic=False)
    make_project(tmp_path, "legacy-1", synthetic=None)     # created before the flag existed
    make_project(tmp_path, "demo-1", synthetic=True)

    async def probe(server):
        async with Client(server) as c:
            listing, _ = await call(c, "list_projects")
            bids, bids_err = await call(c, "list_bids", {"project": "real-1"})
            sel, sel_err = await call(c, "select_bid", {"project": "legacy-1", "tenderer": "Tenderer_X"})
            rub, rub_err = await call(c, "get_rubric", {"project": "real-1"})
            return listing, (bids, bids_err), (sel, sel_err), (rub, rub_err)

    # Default (a client whose model may be in the cloud): synthetic only.
    listing, bids, sel, rub = asyncio.run(probe(make_server(tmp_path)[0]))
    assert "demo-1" in listing and "real-1" not in listing and "legacy-1" not in listing
    assert "2 other project(s) withheld" in listing
    for text, err in (bids, sel, rub):
        assert err and "not flagged synthetic" in text and "local-model client" in text

    # The operator declared an on-premises client: everything is served.
    listing, bids, sel, rub = asyncio.run(probe(make_server(tmp_path, local_model=True)[0]))
    assert "real-1 — Project real-1 [REAL DOCUMENTS]" in listing and "withheld" not in listing
    assert not bids[1] and "Tenderer_X: offer.pdf" in bids[0]
    assert not sel[1] and "Selected bid Tenderer_X of project legacy-1" in sel[0]

    # HTTP: synthetic only, even if MCP_LOCAL_MODEL was set.
    listing, bids, sel, _ = asyncio.run(probe(make_server(tmp_path, transport="http", local_model=True)[0]))
    assert "real-1" not in listing and bids[1] and sel[1] and "HTTP transport" in bids[0]


def test_policy_from_env(monkeypatch):
    monkeypatch.delenv("MCP_LOCAL_MODEL", raising=False)
    assert Policy.from_env("stdio").refusal({"name": "x"}) is not None
    assert Policy.from_env("stdio").refusal({"synthetic": True}) is None
    monkeypatch.setenv("MCP_LOCAL_MODEL", "1")
    assert Policy.from_env("stdio").refusal({"name": "x"}) is None
    assert Policy.from_env("http").refusal({"name": "x"}) is not None


# ---------------------------------------------------------------- HTTP transport

def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_http_transport_requires_api_key_and_serves_synthetic_only(tmp_path):
    import uvicorn
    import pytest
    make_project(tmp_path, "real-1", synthetic=False)
    make_project(tmp_path, "demo-1", synthetic=True)
    server, _ = make_server(tmp_path, transport="http")
    with pytest.raises(RuntimeError, match="API_KEY"):
        build_http_app(server, "")
    port = _free_port()
    us = uvicorn.Server(uvicorn.Config(build_http_app(server, "secret"), host="127.0.0.1",
                                       port=port, log_level="warning"))
    thread = threading.Thread(target=us.run, daemon=True)
    thread.start()
    for _ in range(200):
        if us.started:
            break
        time.sleep(0.05)
    assert us.started
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        for headers in ({}, {"X-API-Key": "wrong"}):
            req = urllib.request.Request(url, data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json", **headers})
            with pytest.raises(HTTPError) as err:
                urllib.request.urlopen(req, timeout=5)
            assert err.value.code == 401

        async def run():
            http = httpx2.AsyncClient(headers={"X-API-Key": "secret"})
            async with Client(streamable_http_client(url, http_client=http)) as c:
                names = {t.name for t in (await c.list_tools()).tools}
                ok, ok_err = await call(c, "select_bid", {"project": "demo-1", "tenderer": "Tenderer_X"})
                no, no_err = await call(c, "select_bid", {"project": "real-1", "tenderer": "Tenderer_X"})
                pages, _ = await call(c, "list_pages")
                return names, (ok, ok_err), (no, no_err), pages

        names, ok, no, pages = asyncio.run(run())
        assert names == TOOLS
        assert not ok[1] and "Selected bid Tenderer_X" in ok[0]
        assert no[1] and "HTTP transport serves synthetic" in no[0]
        assert "offer.pdf p.1 [text]" in pages
    finally:
        us.should_exit = True
        thread.join(timeout=5)


# ---------------------------------------------------------------- local-model client

def scripted(actions) -> FakeLLM:
    """Client actions in order; each answers exactly one prompt that carries a Question."""
    return FakeLLM(rules=[Rule(reply=a, match=r"Question:", times=1) for a in actions])


def test_local_client_answers_with_a_verified_quote(tmp_path):
    make_project(tmp_path, "demo-1", synthetic=True)
    server, ocr = make_server(tmp_path, ocr_budget=2)
    llm = scripted([
        ClientAction(tool="search_pages", query="Non-collusive", thought="search first"),
        ClientAction(tool="ocr_page", page=2, thought="contents says page 2"),
        ClientAction(tool="finish", found=True, page=2, quote=CERT_OCR,
                     answer="Yes — the certificate is on page 2, signed by the director."),
    ])

    async def run():
        async with Client(server) as c:
            return await answer_question("Does the offer include the Non-collusive Tendering "
                                         "Certificate?", c, llm, project="demo-1",
                                         tenderer="Tenderer_X", max_steps=6)

    result = asyncio.run(run())
    assert result["found"] is True and result["page"] == 2 and result["quote"] == CERT_OCR
    assert result["steps"] == 3 and ocr.calls == 1
    assert [s["tool"] for s in result["trace"]] == ["select_bid", "read_page", "search_pages",
                                                    "ocr_page", "finish"]
    assert result["trace"][0]["step"] == 0 and "[skipped]" in result["trace"][0]["result"]
    assert result["trace"][1]["step"] == 0 and "Table of Contents" in result["trace"][1]["result"]


def test_local_client_rejects_unverifiable_quote_then_reports_not_found(tmp_path):
    make_project(tmp_path, "demo-1", synthetic=True)
    server, ocr = make_server(tmp_path)
    llm = scripted([
        ClientAction(tool="finish", found=True, page=3, quote="Certificate enclosed herewith",
                     answer="Yes"),                                   # never read page 3
        ClientAction(tool="read_page", page=1),
        ClientAction(tool="finish", found=True, page=1, quote="Certificate enclosed herewith",
                     answer="Yes"),                                   # read it, but the text is not there
        ClientAction(tool="finish", found=False, answer="Not found in the pages read."),
    ])

    async def run():
        async with Client(server) as c:
            return await answer_question("Is the certificate included?", c, llm,
                                         project="demo-1", tenderer="Tenderer_X", max_steps=6)

    result = asyncio.run(run())
    assert result["found"] is False and result["page"] is None and result["quote"] == ""
    rejected = [s for s in result["trace"] if str(s["result"]).startswith("REJECTED")]
    assert len(rejected) == 2 and ocr.calls == 0
    assert result["steps"] == 4


class _BrokenOCR:
    def ocr_page(self, png_bytes):
        raise RuntimeError("All models in chain failed (qwen3-vl:8b): Connection error.")


def test_ocr_outage_is_reported_to_the_model_not_swallowed(tmp_path):
    make_project(tmp_path, "demo-1", synthetic=True)
    server = build_server(tmp_path, Policy(), llm_factory=lambda cfg: _BrokenOCR())

    async def run():
        async with Client(server) as c:
            await call(c, "select_bid", {"project": "demo-1", "tenderer": "Tenderer_X"})
            return await call(c, "ocr_page", {"page": 2})

    text, err = asyncio.run(run())
    assert err and "OCR unavailable" in text and "Connection error" in text


def test_local_client_step_budget_is_never_a_fabricated_answer(tmp_path):
    make_project(tmp_path, "demo-1", synthetic=True)
    server, _ = make_server(tmp_path)
    llm = scripted([ClientAction(tool="list_pages")] * 3)

    async def run():
        async with Client(server) as c:
            return await answer_question("Anything?", c, llm, project="demo-1", max_steps=3)

    result = asyncio.run(run())
    assert result["found"] is False and "budget exhausted" in result["answer"]
    assert result["trace"][0]["tool"] == "list_bids" and result["trace"][-1]["tool"] == "budget"


def test_local_client_refuses_cloud_endpoints_unless_allowed(monkeypatch):
    import pytest
    monkeypatch.setenv("GITHUB_MODELS_BASE_URL", "http://localhost:11434/v1")
    assert is_local_endpoint("http://localhost:11434/v1")
    assert is_local_endpoint("http://dgx-spark:8000/v1")
    assert is_local_endpoint("http://192.168.1.20:8000/v1")
    assert not is_local_endpoint("https://api.deepseek.com/v1")
    with pytest.raises(SystemExit, match="refusing cloud"):
        build_llm("deepseek-chat@https://api.deepseek.com/v1")
    assert build_llm("deepseek-chat@https://api.deepseek.com/v1", allow_cloud=True).text_chain == [
        "deepseek-chat@https://api.deepseek.com/v1"]
    assert build_llm("qwen3:8b").text_chain == ["qwen3:8b"]


def test_stdio_subprocess_end_to_end(tmp_path):
    # The real server as a subprocess over stdio — the transport Claude Desktop and
    # the local client use. It must start without a model or key, keep stdout clean
    # for the protocol, and (launched the local client's way) serve an unflagged project.
    make_project(tmp_path, "real-1", synthetic=False)

    async def run():
        async with Client(server_params(str(tmp_path))) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            listing, _ = await call(c, "list_projects")
            sel, err = await call(c, "select_bid", {"project": "real-1", "tenderer": "Tenderer_X"})
            page, _ = await call(c, "read_page", {"page": 1})
            return names, listing, (sel, err), page

    names, listing, sel, page = asyncio.run(run())
    assert names == TOOLS
    assert "real-1 — Project real-1 [REAL DOCUMENTS]" in listing
    assert not sel[1] and "offer.pdf p.2 [skipped]" in sel[0]
    assert "Table of Contents" in page


def test_local_client_step_budget_is_the_pipeline_agents(monkeypatch):
    """One shared default (app.config.DEFAULT_AGENT_STEPS) and one override variable
    for both tool-using loops — no second, silently different budget."""
    from app.config import DEFAULT_AGENT_STEPS
    from mcp_server.local_client import build_parser
    monkeypatch.delenv("AGENT_MAX_STEPS", raising=False)
    assert build_parser().parse_args(["q"]).max_steps == DEFAULT_AGENT_STEPS == 8
    monkeypatch.setenv("AGENT_MAX_STEPS", "5")
    assert build_parser().parse_args(["q"]).max_steps == 5
    assert build_parser().parse_args(["q", "--max-steps", "3"]).max_steps == 3

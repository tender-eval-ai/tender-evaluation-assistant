"""MCP server over the Tender Evaluation Assistant's READ-ONLY document tools.

The tools the bounded evidence-search agent uses (`app.tools.BidTools`) — page
listing, keyword search, page read, on-demand OCR with a budget — plus project
navigation, exposed over the Model Context Protocol so any MCP client can walk a
tender or an offer and answer questions with page citations.

CONFIDENTIALITY — the rule that governs this module. Serving a project over MCP sends
every tool result (page listings, snippets, full page text, OCR output) to whatever
model drives the connected client. Claude Desktop, Cursor and similar clients are
driven by cloud models, so connecting them is cloud egress of document content.
Therefore, enforced here rather than left to the operator:

- a project is served ONLY if its meta.json carries `"synthetic": true` (a flag set
  when the project is created; unflagged projects are not even listed);
- unless the operator declares that the connected client's model runs on-premises by
  starting the server with MCP_LOCAL_MODEL=1 — the bundled local-model client
  (mcp_server/local_client.py) does so itself; never set it for a cloud-driven client;
- the HTTP transport is off unless ALLOW_CLOUD_CLIENTS=1, binds to loopback, requires
  X-API-Key (the backend's API_KEY) and serves synthetic projects only whatever
  MCP_LOCAL_MODEL says — an HTTP client can be anywhere.

The server never writes anything except the per-page OCR cache the pipeline shares,
and never prints to stdout (the stdio transport owns it); logs go to stderr.

    python -m mcp_server.server                      # stdio (Claude Desktop, local client)
    python -m mcp_server.server --list               # which projects would be served
    ALLOW_CLOUD_CLIENTS=1 API_KEY=... python -m mcp_server.server --transport http
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import secrets
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.mcpserver import Context, MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp_types import ToolAnnotations  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from app.config import Config, load_dotenv  # noqa: E402
from app.ingest import load_folder  # noqa: E402
from app.schemas import Rubric  # noqa: E402
from app.tools import BidTools  # noqa: E402

log = logging.getLogger("mcp_server")

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                            idempotentHint=True, openWorldHint=False)
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,80}$")
TRUE = ("1", "true", "yes")

INSTRUCTIONS = (
    "Read-only access to tender documents and tenderers' offers held by the Tender "
    "Evaluation Assistant. Workflow: list_projects -> list_bids(project) -> "
    "select_bid(project, tenderer) (or select_tender(project)) -> list_pages / "
    "search_pages / read_page / ocr_page. Pages marked [skipped] are scanned pages "
    "nobody has read yet: search_pages cannot see them — read them with ocr_page, "
    "which has a per-selection budget. Quote page text verbatim and cite the page "
    "number; if the documents do not contain the answer, say so — never infer from "
    "what tenderers usually submit. get_rubric(project) shows the confirmed checklist "
    "the pipeline evaluates against."
)


# ---------------------------------------------------------------- confidentiality policy

@dataclass
class Policy:
    """Which projects this server instance may serve, and why."""
    transport: str = "stdio"      # "stdio" | "http"
    local_model: bool = False     # MCP_LOCAL_MODEL=1: the client's model runs on-premises

    @classmethod
    def from_env(cls, transport: str) -> "Policy":
        return cls(transport=transport,
                   local_model=os.environ.get("MCP_LOCAL_MODEL", "0").lower() in TRUE)

    def refusal(self, meta: dict) -> str | None:
        """None if the project may be served, else the reason it is refused."""
        if meta.get("synthetic") is True:
            return None
        if self.transport == "http":
            return ("refused: this project is not flagged synthetic and the HTTP transport "
                    "serves synthetic/sanitized projects only — a cloud-driven or remote "
                    "client must never see real tender or bid documents (NDA)")
        if self.local_model:
            return None
        return ("refused: this project is not flagged synthetic, and this server was not "
                "started for a local-model client. Real documents may only be read by a "
                "client whose model runs on-premises: use mcp_server/local_client.py "
                "(it starts the server with MCP_LOCAL_MODEL=1), or work on a synthetic "
                "project")

    def describe(self) -> str:
        if self.transport == "http":
            return "HTTP transport: synthetic projects only"
        if self.local_model:
            return "stdio, MCP_LOCAL_MODEL=1: all projects served to the on-premises client"
        return "stdio: synthetic projects only (set MCP_LOCAL_MODEL=1 for an on-premises client)"


# ---------------------------------------------------------------- server

class LazyLLM:
    """Builds the vision client on first use, so listing and reading pages never
    needs a model (or a key) at all."""

    def __init__(self, factory: Callable[[Config], object], cfg: Config):
        self._factory, self._cfg, self._llm = factory, cfg, None

    def ocr_page(self, png_bytes: bytes) -> str:
        if self._llm is None:
            self._llm = self._factory(self._cfg)
        return self._llm.ocr_page(png_bytes)


@dataclass
class Selection:
    project: str
    target: str            # "tender" | "bid <tenderer>"
    tools: BidTools


@dataclass
class ConnectionState:
    """Per-connection state: which documents this client is reading. The SDK enters
    the server lifespan once per connection (stdio process, HTTP session), so the
    object dies with the connection — no registry, nothing to leak."""
    selection: Selection | None = None


@asynccontextmanager
async def _lifespan(_server: MCPServer) -> AsyncIterator[ConnectionState]:
    yield ConnectionState()


def default_cfg(pdir: Path) -> Config:
    cfg = Config()
    cfg.cache_dir = pdir / "work" / "cache"     # shared with the pipeline's OCR cache
    return cfg


def default_llm(cfg: Config):
    from app.llm import LLM
    return LLM(cfg)


def build_server(data_dir: Path, policy: Policy,
                 cfg_factory: Callable[[Path], Config] = default_cfg,
                 llm_factory: Callable[[Config], object] = default_llm) -> MCPServer:
    """Register the tools on an MCPServer. Selections (which documents a client is
    reading) are per connection; `cfg_factory` / `llm_factory` exist so tests can
    inject a stub vision model."""
    projects_dir = data_dir / "projects"
    server = MCPServer("tender-evaluation-assistant", instructions=INSTRUCTIONS,
                       lifespan=_lifespan)

    # ------------------------------------------------------------ helpers
    def _project(pid: str) -> tuple[Path, dict]:
        if not pid or not NAME_RE.match(pid):
            raise ToolError(f"unknown project '{pid}' — call list_projects")
        pdir = projects_dir / pid
        if not (pdir / "meta.json").is_file():
            raise ToolError(f"unknown project '{pid}' — call list_projects")
        meta = json.loads((pdir / "meta.json").read_text())
        why = policy.refusal(meta)
        if why:
            raise ToolError(why)
        return pdir, meta

    def _bidders(pdir: Path) -> list[Path]:
        bids = pdir / "bids"
        if not bids.is_dir():
            return []
        return sorted(p for p in bids.iterdir() if p.is_dir() and not p.name.startswith("."))

    def _pdfs(folder: Path) -> list[Path]:
        return sorted(p for p in folder.rglob("*.pdf") if not p.name.startswith("~$"))

    def _select(ctx: Context, pdir: Path, folder: Path, target: str) -> str:
        cfg = cfg_factory(pdir)
        docs = load_folder(folder, cfg, None, cached_only=True)
        if not docs:
            raise ToolError(f"no PDF files for {target} of project {pdir.name}")
        tools = BidTools(docs, cfg, LazyLLM(llm_factory, cfg), cfg.agent_ocr_pages)
        ctx.request_context.lifespan_context.selection = Selection(pdir.name, target, tools)
        pages = sum(len(d.pages) for d in docs)
        unread = sum(1 for d in docs for p in d.pages if p.source == "skipped")
        head = f"Selected {target} of project {pdir.name}: {len(docs)} file(s), {pages} page(s)."
        if unread:
            head += (f" {unread} scanned page(s) are [skipped] — not read yet: use ocr_page(page) "
                     f"(budget {cfg.agent_ocr_pages} page(s) for this selection; a local vision "
                     "model needs ~25 s per page).")
        return head + "\n" + tools.list_pages()

    def _sel(ctx: Context) -> Selection:
        sel = ctx.request_context.lifespan_context.selection
        if sel is None:
            raise ToolError("no documents selected — call select_bid(project, tenderer) "
                            "or select_tender(project) first")
        return sel

    # ------------------------------------------------------------ navigation tools
    @server.tool(annotations=READ_ONLY)
    def list_projects() -> str:
        """Projects this server may serve: id, name, tenderers. Projects not flagged
        synthetic are withheld unless the server was started for an on-premises client."""
        lines, withheld = [], 0
        for meta_path in sorted(projects_dir.glob("*/meta.json")):
            meta = json.loads(meta_path.read_text())
            if policy.refusal(meta):
                withheld += 1
                continue
            pdir = meta_path.parent
            tenderers = ", ".join(p.name for p in _bidders(pdir)) or "none"
            flag = "synthetic" if meta.get("synthetic") is True else "REAL DOCUMENTS"
            lines.append(f"{pdir.name} — {meta.get('name', '')} [{flag}] — tenderers: {tenderers}")
        if withheld:
            lines.append(f"({withheld} other project(s) withheld: not flagged synthetic — "
                         f"{policy.describe()})")
        return "\n".join(lines) or "no projects"

    @server.tool(annotations=READ_ONLY)
    def list_bids(project: str) -> str:
        """Tenderers of a project with their offer files and page counts."""
        pdir, _ = _project(project)
        out = []
        for b in _bidders(pdir):
            files = [f"{p.name} ({len(PdfReader(str(p)).pages)} pages)" for p in _pdfs(b)]
            out.append(f"{b.name}: {', '.join(files) or 'no PDF'}")
        tender = _pdfs(pdir / "tender")
        head = f"Project {pdir.name}: tender documents {', '.join(p.name for p in tender) or 'none'}"
        return head + "\n" + ("\n".join(out) or "no tenderers")

    @server.tool(annotations=READ_ONLY)
    def get_rubric(project: str) -> str:
        """The confirmed evaluation rubric (Stage I checklist, Stage II essential
        requirements, price scheme), if the pipeline has derived one."""
        pdir, _ = _project(project)
        path = pdir / "work" / "rubric.json"
        if not path.is_file():
            return "no rubric yet — the pipeline has not been run on this project"
        r = Rubric.model_validate_json(path.read_text())
        lines = [f"Tender ref: {r.tender_ref}", "Stage I checklist (required documents):"]
        lines += [f"  {i.id}: {i.item}{'' if i.required else ' (optional)'}" for i in r.stage1_checklist]
        lines.append("Stage II essential requirements:")
        lines += [f"  {q.id}: {q.requirement}" for q in r.stage2_requirements]
        ps = r.price_scheme
        lines.append(f"Price scheme: {ps.type}, quantity {ps.quantity} {ps.unit or ''}".rstrip())
        return "\n".join(lines)

    @server.tool(annotations=READ_ONLY)
    def select_tender(project: str, ctx: Context) -> str:
        """Open a project's tender documents for reading; returns the page listing."""
        pdir, _ = _project(project)
        return _select(ctx, pdir, pdir / "tender", "tender")

    @server.tool(annotations=READ_ONLY)
    def select_bid(project: str, tenderer: str, ctx: Context) -> str:
        """Open one tenderer's offer for reading; returns the page listing. Pages
        marked [skipped] are scanned pages nobody has read yet (see ocr_page)."""
        pdir, _ = _project(project)
        match = next((b for b in _bidders(pdir) if b.name == tenderer), None)
        if match is None:
            raise ToolError(f"unknown tenderer '{tenderer}' — tenderers: "
                            f"{', '.join(b.name for b in _bidders(pdir)) or 'none'}")
        return _select(ctx, pdir, match, f"bid {match.name}")

    # ------------------------------------------------------------ document tools
    @server.tool(annotations=READ_ONLY)
    def list_pages(ctx: Context) -> str:
        """Every page of the selected documents: file, number, source (text | ocr |
        skipped = not read yet) and a one-line preview."""
        return _sel(ctx).tools.list_pages()

    @server.tool(annotations=READ_ONLY)
    def search_pages(query: str, ctx: Context, top_k: int = 5) -> str:
        """Pages already read that mention the query, best first, with snippets.
        Skipped pages cannot match — read them with ocr_page first."""
        return _sel(ctx).tools.search_pages(query, top_k)

    @server.tool(annotations=READ_ONLY)
    def read_page(page: int, ctx: Context, file: str | None = None) -> str:
        """Full text of a page already read (1-based; `file` for multi-file selections)."""
        try:
            return _sel(ctx).tools.read_page(page, file)
        except ValueError as err:
            raise ToolError(str(err)) from err

    @server.tool(annotations=READ_ONLY)
    def ocr_page(page: int, ctx: Context, file: str | None = None) -> str:
        """Read a skipped (scanned) page through the vision model — limited budget per
        selection; the transcription is cached for the pipeline as well."""
        try:
            return _sel(ctx).tools.ocr_page(page, file)
        except ValueError as err:
            raise ToolError(str(err)) from err

    return server


# ---------------------------------------------------------------- HTTP transport guard

class ApiKeyMiddleware:
    """ASGI middleware: every HTTP request must carry X-API-Key (the backend's key)."""

    def __init__(self, app, api_key: str):
        if not api_key:
            raise RuntimeError("API_KEY must be set for the HTTP transport")
        self.app, self.api_key = app, api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            if not secrets.compare_digest(headers.get("x-api-key", ""), self.api_key):
                from starlette.responses import JSONResponse
                await JSONResponse({"detail": "invalid or missing X-API-Key"},
                                   status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_http_app(server: MCPServer, api_key: str, host: str = "127.0.0.1"):
    """Streamable-HTTP app (endpoint /mcp) behind the API-key check."""
    return ApiKeyMiddleware(server.streamable_http_app(host=host), api_key)


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transport", choices=["stdio", "http"],
                        default=os.environ.get("MCP_TRANSPORT", "stdio"))
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address (loopback)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "8765")))
    parser.add_argument("--data-dir", default=os.environ.get("DATA_DIR", "data"),
                        help="the backend's data directory (default: data/ under the repo)")
    parser.add_argument("--list", action="store_true",
                        help="print the projects this server would serve, then exit")
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    policy = Policy.from_env(args.transport)
    server = build_server(data_dir, policy)

    if args.list:
        print(policy.describe())
        # A direct call of the registered function — no client involved.
        print(server._tool_manager.get_tool("list_projects").fn())  # type: ignore[attr-defined]
        return 0

    if args.transport == "http":
        if os.environ.get("ALLOW_CLOUD_CLIENTS", "0").lower() not in TRUE:
            log.error("HTTP transport is off: set ALLOW_CLOUD_CLIENTS=1 to serve SYNTHETIC "
                      "projects to cloud-driven or remote clients")
            return 2
        api_key = os.environ.get("API_KEY", "")
        if not api_key:
            log.error("HTTP transport needs API_KEY (the backend's key) — refusing to start")
            return 2
        if args.host not in ("127.0.0.1", "localhost", "::1"):
            log.warning("binding to %s — anything beyond loopback must be firewalled", args.host)
        import uvicorn
        log.info("%s; http://%s:%d/mcp", policy.describe(), args.host, args.port)
        uvicorn.run(build_http_app(server, api_key, args.host), host=args.host,
                    port=args.port, log_level="info")
        return 0

    log.info("%s; data dir %s", policy.describe(), data_dir)
    server.run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())

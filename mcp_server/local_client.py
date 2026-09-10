"""Local-model MCP client — the production-compatible way to use the MCP server.

Connects to mcp_server/server.py over stdio (launching it as a subprocess with
MCP_LOCAL_MODEL=1) and drives its tools with the project's own OpenAI-compatible
`LLM` class pointed at a LOCAL endpoint (Ollama on a laptop, vLLM on the DGX Spark),
so the whole loop — tool execution and the model that reads the results — stays on
the machine that holds the documents. Same guardrails as the pipeline's
evidence-search agent: schema-validated JSON actions, a step budget, the server's OCR
budget, and a quote-on-page check — `finish(found=true)` is accepted only if the quoted
text is on a page this client actually read, so the failure mode is "not found",
never a fabricated citation.

    python -m mcp_server.local_client "Does the offer include the Non-collusive \
        Tendering Certificate?" --project <project-id> --tenderer Tenderer_C

A cloud text endpoint is refused unless --allow-cloud-model is given (synthetic
projects only — that variant is the *cloud-driven client* of the experiment).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import Client  # noqa: E402
from mcp.client.stdio import StdioServerParameters  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from app.config import Config, load_dotenv  # noqa: E402
from app.grounding import quote_on_page  # noqa: E402

DEFAULT_MODEL = "qwen3:8b@http://localhost:11434/v1"
RESULT_CHARS = 4000
TRACE_CHARS = 300

SYSTEM = (
    "You answer a procurement reviewer's question about a tender or a tenderer's offer "
    "by calling tools on a document server and reading the results. Tools:\n"
    "list_projects() ; list_bids(project) ; get_rubric(project) ; "
    "select_tender(project) / select_bid(project, tenderer) -> open documents, returns the "
    "page listing ; list_pages() ; search_pages(query) -> pages already read that mention "
    "the query ; read_page(page[, file]) -> full text of a page already read ; "
    "ocr_page(page[, file]) -> read a [skipped] scanned page (limited budget) ; "
    "finish(found, answer, page, quote) -> end.\n"
    "Rules: one action per step. Pages marked [skipped] have not been read — search "
    "cannot see them; if a table of contents or cover page points to one, ocr_page it. "
    "finish(found=true) must cite a page you read with read_page or ocr_page and quote "
    "its text verbatim; the quote is checked and an unverifiable one is rejected. "
    "found=false with an explanation is the correct answer when the documents do not "
    "contain it. Never infer from what tenderers usually submit. Steps are limited; "
    "finish as soon as you know the answer."
)


class ClientAction(BaseModel):
    """One step: a tool call on the MCP server, or `finish`."""
    thought: str = Field(default="", description="One sentence: why this step")
    tool: Literal["list_projects", "list_bids", "get_rubric", "select_tender", "select_bid",
                  "list_pages", "search_pages", "read_page", "ocr_page", "finish"]
    project: Optional[str] = Field(default=None, description="project id (navigation tools)")
    tenderer: Optional[str] = Field(default=None, description="select_bid only")
    query: str = Field(default="", description="search_pages only")
    page: Optional[int] = Field(default=None, description="read_page / ocr_page / finish")
    file: Optional[str] = Field(default=None, description="file name for multi-file selections")
    found: bool = Field(default=False, description="finish only: evidence found and quoted")
    answer: str = Field(default="", description="finish only: the answer for the reviewer")
    quote: str = Field(default="", description="finish only: verbatim text from the cited page")


def tool_args(a: ClientAction) -> dict:
    if a.tool in ("list_bids", "get_rubric", "select_tender"):
        return {"project": a.project or ""}
    if a.tool == "select_bid":
        return {"project": a.project or "", "tenderer": a.tenderer or ""}
    if a.tool == "search_pages":
        return {"query": a.query}
    if a.tool in ("read_page", "ocr_page"):
        args: dict = {"page": a.page if a.page is not None else 0}
        if a.file:
            args["file"] = a.file
        return args
    return {}


def _text(result) -> str:
    return "\n".join(getattr(c, "text", "") for c in result.content) or "(empty)"


async def answer_question(question: str, client: Client, llm, *, project: str | None = None,
                          tenderer: str | None = None, max_steps: int = 10,
                          log=None) -> dict:
    """The loop. `client` is a connected `mcp.Client` (stdio subprocess in production,
    in-process server in tests); `llm` anything with the project's `chat_json`."""
    log = log or (lambda *_: None)
    transcript = [f"Question: {question}"]
    trace: list[dict] = []
    seen: dict[int, list[str]] = {}      # page number -> texts this client read
    t0 = time.time()

    async def call(tool: str, args: dict) -> tuple[str, bool]:
        r = await client.call_tool(tool, args)
        return _text(r), bool(r.is_error)

    # Initial observation: orient the model without spending its steps.
    if project and tenderer:
        first = ("select_bid", {"project": project, "tenderer": tenderer})
    elif project:
        first = ("list_bids", {"project": project})
    else:
        first = ("list_projects", {})
    text, is_error = await call(*first)
    trace.append({"step": 0, "tool": first[0], "args": first[1], "result": text[:TRACE_CHARS]})
    transcript.append(f"Initial observation — {first[0]}({first[1]}) ->\n{text[:RESULT_CHARS]}")
    log(f"[0] {first[0]}{first[1]} -> {text[:120]!r}")
    if first[0] == "select_bid" and not is_error:
        # Same lesson as the pipeline's agent: show the cover / contents page up front,
        # or the model hunts through filler pages instead of following the contents.
        page1, is_error = await call("read_page", {"page": 1})
        if not is_error:
            seen.setdefault(1, []).append(page1)
        trace.append({"step": 0, "tool": "read_page", "args": {"page": 1}, "result": page1[:TRACE_CHARS]})
        transcript.append(f"Page 1 (cover / contents) reads:\n{page1[:1500]}")
        log(f"[0] read_page(1) -> {page1[:120]!r}")

    for step in range(1, max_steps + 1):
        prompt = "\n\n".join(transcript) + f"\n\nStep {step}: choose your next action."
        action: ClientAction = await asyncio.to_thread(llm.chat_json, SYSTEM, prompt, ClientAction)
        if action.tool == "finish":
            if action.found:
                texts = seen.get(action.page if action.page is not None else -1, [])
                if not any(quote_on_page(action.quote, t) for t in texts):
                    if action.page is None:
                        result = ("REJECTED: finish(found=true) needs `page` — the number of the "
                                  "page you read the evidence on — and `quote` copied verbatim "
                                  "from it. Set both, or finish with found=false.")
                    elif action.page not in seen:
                        result = (f"REJECTED: you have not read page {action.page} in this session "
                                  f"— call read_page({action.page}) or ocr_page({action.page}) "
                                  "first, then quote it verbatim, or finish with found=false.")
                    else:
                        result = (f"REJECTED: the quote does not appear verbatim on page "
                                  f"{action.page} as read in this session. Copy the text exactly "
                                  "from that page, or finish with found=false.")
                    trace.append({"step": step, "thought": action.thought, "tool": "finish",
                                  "args": {"page": action.page, "quote": action.quote[:200]},
                                  "result": result})
                    transcript.append(f"Step {step}: finish(found=true, page={action.page}) -> {result}")
                    log(f"[{step}] finish rejected: quote not on page {action.page}")
                    continue
            trace.append({"step": step, "thought": action.thought, "tool": "finish",
                          "args": {"found": action.found, "page": action.page,
                                   "quote": action.quote[:200]}, "result": "accepted"})
            log(f"[{step}] finish(found={action.found}, page={action.page})")
            return {"question": question, "found": action.found, "answer": action.answer,
                    "page": action.page if action.found else None,
                    "quote": action.quote if action.found else "",
                    "steps": step, "seconds": round(time.time() - t0, 1), "trace": trace}
        args = tool_args(action)
        result, is_error = await call(action.tool, args)
        if action.tool in ("read_page", "ocr_page") and not is_error and action.page is not None:
            seen.setdefault(action.page, []).append(result)
        trace.append({"step": step, "thought": action.thought, "tool": action.tool,
                      "args": args, "result": result[:TRACE_CHARS]})
        transcript.append(f"Step {step}: {action.tool}({args}) ->\n{result[:RESULT_CHARS]}")
        log(f"[{step}] {action.tool}{args} -> {result[:120]!r}")

    trace.append({"step": max_steps, "tool": "budget", "args": {},
                  "result": "step budget exhausted — no verified answer"})
    return {"question": question, "found": False,
            "answer": "step budget exhausted without a verified answer", "page": None,
            "quote": "", "steps": max_steps, "seconds": round(time.time() - t0, 1),
            "trace": trace}


# ---------------------------------------------------------------- wiring

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}


def is_local_endpoint(base_url: str) -> bool:
    """Loopback, private-range or bare LAN hostnames count as on-premises."""
    host = (urlparse(base_url).hostname or "").lower()
    if host in LOCAL_HOSTS:
        return True
    if host.startswith(("10.", "192.168.")) or re.match(r"^172\.(1[6-9]|2\d|3[01])\.", host):
        return True
    return bool(host) and "." not in host


def build_llm(model: str, allow_cloud: bool = False):
    """The project's LLM class on one model entry, refusing cloud endpoints unless
    explicitly allowed (synthetic projects only)."""
    from app.llm import LLM
    cfg = Config()
    cfg.text_model, cfg.text_fallbacks = model, []
    _, _, url = model.partition("@")
    base = url or cfg.base_url
    if not is_local_endpoint(base) and not allow_cloud:
        raise SystemExit(f"refusing cloud text endpoint {base}: the local client keeps documents "
                         "on-premises. Pass --allow-cloud-model for a SYNTHETIC project only.")
    return LLM(cfg)


def server_params(data_dir: str | None = None) -> StdioServerParameters:
    """Launch the server as a subprocess, declaring an on-premises client."""
    env = {**os.environ, "MCP_LOCAL_MODEL": "1"}
    if data_dir:
        env["DATA_DIR"] = data_dir
    return StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"],
                                 cwd=str(ROOT), env=env)


async def _run(args) -> dict:
    llm = build_llm(args.model, args.allow_cloud_model)
    async with Client(server_params(args.data_dir)) as client:
        return await answer_question(args.question, client, llm, project=args.project,
                                     tenderer=args.tenderer, max_steps=args.max_steps,
                                     log=lambda m: print(m, file=sys.stderr))


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question")
    parser.add_argument("--project", help="project id (see: python -m mcp_server.server --list)")
    parser.add_argument("--tenderer", help="open this tenderer's offer before the first step")
    parser.add_argument("--model", default=os.environ.get("LOCAL_TEXT_MODEL", DEFAULT_MODEL),
                        help="model[@base_url] driving the tools (default: %(default)s)")
    parser.add_argument("--allow-cloud-model", action="store_true",
                        help="permit a cloud endpoint — SYNTHETIC projects only")
    parser.add_argument("--max-steps", type=int, default=int(os.environ.get("AGENT_MAX_STEPS", "10")),
                        help="step budget per question (default: AGENT_MAX_STEPS if set, else 10 — "
                             "the pipeline's own agent defaults to 8)")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--trace", help="write the full result (answer + step trace) to this JSON file")
    args = parser.parse_args(argv)

    result = asyncio.run(_run(args))
    if args.trace:
        Path(args.trace).write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in result.items() if k != "trace"}, indent=2, ensure_ascii=False))
    return 0 if result["found"] or result["steps"] < args.max_steps else 1


if __name__ == "__main__":
    sys.exit(main())

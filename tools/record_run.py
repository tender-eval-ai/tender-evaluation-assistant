"""Record one project's run from a running API, for the guest site: every response the UI reads
for it, every page image it shows, and the Word reports, as static files the UI replays with
VITE_REPLAY=1 (web/src/api.js). Nothing is written back to the API.

    python tools/record_run.py --api http://localhost:8000 --pid showcase-small-tender-1a2b3c \\
        --out replay --source-url https://github.com/tender-eval-ai/tender-evaluation-assistant
    # -> replay/ (api/, img/, manifest.json) and replay-<date>.tar.gz beside it

A file's name is route_key() of the path it answers, the same function web/src/replayKey.js
applies in the browser (test/data/replay_keys.json holds the vectors both are tested with).
Page images are saved as JPEG, 1100 px wide at most. Record a synthetic project only: the files
are published."""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
import tarfile
from itertools import combinations
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlsplit

DROPPED = ("sig", "exp")          # a signed link's signature: not part of what the file answers
WIDTH = 1100


def fnv1a(text: str) -> str:
    h = 0x811C9DC5
    for byte in text.encode():
        h = ((h ^ byte) * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def route_key(path_and_query: str) -> str:
    """A file name for a GET path: the path without its leading slash, the query's parameters
    sorted (a signature dropped), every character but letters, digits, '.' and '-' written as
    '_' and its UTF-8 bytes in hex; a long one cut and given a hash of the whole."""
    parts = urlsplit(path_and_query)
    pairs = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in DROPPED)
    text = unquote(parts.path).strip("/") + ("?" + "&".join(f"{k}={v}" for k, v in pairs) if pairs else "")
    key = "".join(c if (c.isascii() and (c.isalnum() or c in ".-")) else "".join(f"_{b:02x}" for b in c.encode())
                  for c in text)
    return key if len(key) <= 150 else f"{key[:100]}-{fnv1a(key)}"


class Recorder:
    def __init__(self, api: str, key: str | None, out: Path):
        import requests
        self.api, self.out, self.s = api.rstrip("/"), out, requests.Session()
        if key:
            self.s.headers["X-API-Key"] = key
        (out / "api").mkdir(parents=True, exist_ok=True)
        (out / "img").mkdir(parents=True, exist_ok=True)
        self.saved: set[str] = set()
        self.images: set[str] = set()

    def get(self, path: str, required: bool = True):
        r = self.s.get(self.api + path, timeout=120)
        if r.status_code >= 400:
            if required:
                raise RuntimeError(f"GET {path} -> {r.status_code}: {r.text[:200]}")
            return None
        key = route_key(path)
        (self.out / "api" / key).write_bytes(r.content)
        self.saved.add(key)
        return r.json() if "json" in r.headers.get("content-type", "") else r.content

    def put(self, path: str, body) -> None:
        """A response the recording answers with, not the API (the guest site's own settings)."""
        key = route_key(path)
        (self.out / "api" / key).write_text(json.dumps(body))
        self.saved.add(key)

    def image(self, url: str) -> None:
        key = route_key(url) + ".jpg"
        if key in self.images:
            return
        r = self.s.get(self.api + url, timeout=120)
        if r.status_code >= 400:
            raise RuntimeError(f"GET {url} -> {r.status_code}")
        from PIL import Image
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        if im.width > WIDTH:
            im = im.resize((WIDTH, round(im.height * WIDTH / im.width)))
        im.save(self.out / "img" / key, "JPEG", quality=72, optimize=True)
        self.images.add(key)


def urls_in(node) -> list[str]:
    if isinstance(node, dict):
        return [u for k, v in node.items() for u in ([v] if k == "image_url" and isinstance(v, str) else urls_in(v))]
    if isinstance(node, list):
        return [u for v in node for u in urls_in(v)]
    return []


def citations_in(ruleset: dict) -> list[dict]:
    out = []
    for item in ruleset.get("items", []):
        out += [item.get("citation")] + list(item.get("clauses") or [])
        out += [s.get("citation") for s in (item.get("slots") or {}).values()]
        out += [n.get("citation") for n in item.get("notes") or []]
    for part in ruleset.get("parts", []):
        out += [part.get("citation")] + list(part.get("clauses") or [])
    return [c for c in out if c and c.get("quote") and c.get("page")]


def record(api: str, key: str | None, pid: str, out: Path, source_url: str, log=print) -> dict:
    rec = Recorder(api, key, out)
    p = f"/projects/{quote(pid, safe='')}"
    project = rec.get(p)
    rec.put("/projects", [{k: project[k] for k in ("id", "name", "synthetic", "data_class", "created") if k in project}])
    rec.put("/settings", {"hosted_demo": True, "data_classes": ["synthetic"], "uploads": False, "source_url": source_url})
    rec.put("/inbox", [])

    versions = rec.get(f"{p}/ruleset/versions")
    numbers = [v["version"] for v in versions]
    confirmed = [v["version"] for v in versions if v["status"] == "confirmed"]
    rulesets = [rec.get(f"{p}/ruleset")] + [rec.get(f"{p}/ruleset?version={n}") for n in numbers]
    rec.get(f"{p}/ruleset/gaps")
    for a, b in combinations(numbers, 2):
        rec.get(f"{p}/ruleset/diff?from={a}&to={b}")

    documents = rec.get(f"{p}/documents")
    pages = {}
    for doc in documents:
        pages[doc["doc_id"]] = rec.get(f"{p}/documents/{quote(doc['doc_id'], safe='')}/pages")
        for page in pages[doc["doc_id"]]:
            rec.image(page["image_url"])
    by_path = {d.get("path") or d["file"]: d["doc_id"] for d in documents}
    for c in {(c["file"], c["page"], c["quote"]) for rs in rulesets for c in citations_in(rs)}:
        doc_id = by_path.get(c[0])
        page = next((pg for pg in pages.get(doc_id, []) if pg.get("page") == c[1] or pg.get("n") == c[1]), None)
        if page is not None:
            rec.image(f"{page['image_url']}{'&' if '?' in page['image_url'] else '?'}highlight={quote(c[2])}")

    jobs = rec.get(f"{p}/jobs")
    for job in jobs.get("items", []):
        rec.get(f"{p}/jobs/{quote(job['job_id'], safe='')}")
    rec.get(f"{p}/events")
    for tenderer in project.get("bidders") or []:
        t = quote(tenderer, safe="")
        result = rec.get(f"{p}/bids/{t}/results", required=False)
        if result is None:
            continue
        rec.get(f"{p}/bids/{t}/results?version={result['ruleset_version']}")
        for url in urls_in(result):
            rec.image(url)
    for v in [None, *confirmed]:
        suffix = "" if v is None else f"?version={v}"
        rec.get(f"{p}/price-summary{suffix}", required=False)
        evaluation = rec.get(f"{p}/evaluation{suffix}", required=False)
        for url in urls_in(evaluation or {}):
            rec.image(url)
        for report in rec.get(f"{p}/reports{suffix}", required=False) or []:
            rec.get(f"{p}/reports/{quote(report['name'], safe='')}{suffix}", required=False)

    when = dt.datetime.now(dt.timezone.utc)
    manifest = {"recorded_at": when.isoformat(timespec="seconds"), "label": f"Recorded run · {when:%-d %B %Y}",
                "project": {"id": project["id"], "name": project["name"]}, "responses": len(rec.saved),
                "images": len(rec.images)}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    log(f"recorded {len(rec.saved)} responses and {len(rec.images)} page images of {project['id']} into {out}")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--key", default=None)
    ap.add_argument("--pid", required=True, help="a synthetic project, checked and reviewed (tools/seed_showcase.py)")
    ap.add_argument("--out", type=Path, default=Path("replay"))
    ap.add_argument("--source-url", default="https://github.com/tender-eval-ai/tender-evaluation-assistant")
    args = ap.parse_args()
    try:
        manifest = record(args.api, args.key, args.pid, args.out, args.source_url)
    except RuntimeError as err:
        print(f"record_run: {err}", file=sys.stderr)
        return 1
    bundle = args.out.parent / f"replay-{manifest['recorded_at'][:10]}.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        tar.add(args.out, arcname="replay")
    print(f"bundle: {bundle} ({bundle.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

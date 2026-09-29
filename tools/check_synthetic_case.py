"""The synthetic tender case end to end through the API: a project, the case imported from
the inbox, the fixture rule set as a draft confirmed by a second person, one check per
tenderer on the worker, and the results.

    python tools/check_synthetic_case.py                       # against http://localhost:8000
    python tools/check_synthetic_case.py --api http://host:8000 --key sesame --tenderers Tenderer_B

Prints one line per tenderer: the Stage I and II outcomes, the items by outcome, the verdict
for item (l), the signature read, its page, its confidence and whether V4 verified it, and
the model calls the check cost. `--ruleset test/data/synthetic_tender/ruleset_all_items.json` checks
every item; the default rule set names item (l) alone. Exit code 1 if a job failed or the API refused a step."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULESET = ROOT / "test" / "data" / "synthetic_tender" / "ruleset_item_l.json"


class Api:
    """A thin client over `requests` (or anything with the same .request), rooted at `base`."""

    def __init__(self, session, base: str = "", key: str | None = None):
        self.session, self.base, self.key = session, base.rstrip("/"), key

    def call(self, method: str, path: str, user: str | None = None, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        if self.key:
            headers["X-API-Key"] = self.key
        if user:
            headers["X-User"] = user
        r = self.session.request(method, f"{self.base}{path}", headers=headers, **kwargs)
        if r.status_code >= 400:
            try:
                err = r.json().get("error", {})
            except ValueError:
                err = {}
            raise RuntimeError(f"{method} {path} -> {r.status_code} {err.get('code', '')}: {err.get('message', r.text[:200])}")
        return r.json() if r.content else None


def run(api: Api, case: str = "synthetic_tender", ruleset_path: Path = DEFAULT_RULESET, tenderers: list[str] | None = None,
        timeout: float = 900.0, log=print) -> list[dict]:
    project = api.call("POST", "/projects", json={"name": f"synthetic case {case}", "data_class": "synthetic"})
    pid = project["id"]
    imported = api.call("POST", f"/projects/{pid}/import", json={"path": case, "kind": "case"})
    log(f"project {pid}: {imported['tender_pdfs']} tender documents, offers from {', '.join(sorted(imported['bidders']))}")

    ruleset = json.loads(Path(ruleset_path).read_text())
    named = sorted({i["template"] for i in ruleset["items"] if i.get("template")})
    health = api.call("GET", "/health")
    log(f"templates in the API's library: {health.get('templates')}")
    if named and not health.get("templates"):
        log(f"WARNING: the rule set names templates ({', '.join(named)}) but the library is empty, so their items "
            f"come out needs_review; set RULESET_TEMPLATES_DIR for the API and the worker")
    draft = {k: v for k, v in ruleset.items() if k not in ("status", "confirmed_by", "confirmed_at", "version", "project_id")}
    api.call("PUT", f"/projects/{pid}/ruleset/draft", user="chenyu", json=draft)
    confirmed = api.call("POST", f"/projects/{pid}/ruleset/confirm", user="nasi")
    log(f"rule set v{confirmed['version']} confirmed by {confirmed['confirmed_by']}: "
        f"{', '.join(f'({i['letter']})' for i in confirmed['items'])}")

    body = {"tenderers": tenderers} if tenderers else {}
    jobs = api.call("POST", f"/projects/{pid}/checks", user="chenyu", json=body)["job_ids"]
    log(f"{len(jobs)} checks started")
    deadline = time.time() + timeout
    pending = dict(jobs)
    while pending and time.time() < deadline:
        for tenderer, job_id in list(pending.items()):
            job = api.call("GET", f"/projects/{pid}/jobs/{job_id}")
            if job["state"] in ("done", "failed", "dead"):
                log(f"  {tenderer}: {job['state']}" + (f" ({job['error']})" if job.get("error") else ""))
                del pending[tenderer]
        time.sleep(1.0)
    if pending:
        log(f"still running after {timeout:.0f} s: {', '.join(sorted(pending))} (the jobs continue on the worker; "
            f"GET /projects/{pid}/jobs to follow them)")

    rows = []
    for tenderer in sorted(jobs):
        job = api.call("GET", f"/projects/{pid}/jobs/{jobs[tenderer]}")
        if job["state"] != "done":
            rows.append({"tenderer": tenderer, "state": job["state"], "error": job.get("error"),
                         "reason": f"{job.get('step') or ''} {job.get('progress') or ''}".strip() if job["state"] == "running" else None})
            continue
        res = api.call("GET", f"/projects/{pid}/bids/{tenderer}/results")
        verdict = res["verdicts"].get("l") or {"outcome": res["stage1"]["outcome"], "reason": ""}
        signature = res["fields"].get("l", {}).get("signature", {})
        counts: dict[str, int] = {}
        for outcome in res["stage1"]["items"].values():
            counts[outcome] = counts.get(outcome, 0) + 1
        rows.append({"tenderer": tenderer, "state": "done", "outcome": verdict["outcome"], "reason": verdict["reason"],
                     "stage1": res["stage1"]["outcome"], "stage2": (res.get("stage2") or {}).get("outcome"),
                     "items": ", ".join(f"{n} {o}" for o, n in sorted(counts.items())),
                     "signature": signature.get("value"), "page": (signature.get("page") or {}).get("page"),
                     "confidence": signature.get("confidence"), "verified": (signature.get("verification") or {}).get("verified"),
                     "calls": res["cost"].get("calls"), "usd": res["cost"].get("usd")})
    return rows


def table(rows: list[dict]) -> str:
    lines = [f"{'tenderer':<12} {'state':<7} {'stage I':<13} {'stage II':<9} {'items':<34} {'item (l)':<13} {'signature':<24} "
             f"{'page':>4} {'conf':>5} {'verified':<8} {'calls':>5} {'usd':>8}  reason"]
    for r in rows:
        lines.append(f"{r['tenderer']:<12} {r['state']:<7} {str(r.get('stage1', '-')):<13} {str(r.get('stage2', '-')):<9} "
                     f"{str(r.get('items', '-')):<34} {r.get('outcome', '-'):<13} {str(r.get('signature', '-')):<24} "
                     f"{str(r.get('page', '-')):>4} {str(r.get('confidence', '-')):>5} {str(r.get('verified', '-')):<8} "
                     f"{str(r.get('calls', '-')):>5} {str(r.get('usd', '-')):>8}  "
                     f"{r.get('reason') or r.get('error') or ''}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--key", default=None, help="X-API-Key, when the API requires one")
    parser.add_argument("--case", default="synthetic_tender", help="folder name in the API's inbox")
    parser.add_argument("--ruleset", default=str(DEFAULT_RULESET))
    parser.add_argument("--tenderers", nargs="*")
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args(argv)
    import requests
    rows = run(Api(requests.Session(), args.api, args.key), args.case, Path(args.ruleset), args.tenderers, args.timeout)
    print(table(rows))
    return 0 if all(r["state"] == "done" for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())

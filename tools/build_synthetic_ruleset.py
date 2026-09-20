"""The rule builder on the synthetic case through the API: a project, the case imported
from the inbox, `POST /ruleset/build` on the worker, the draft it saves.

    python tools/build_synthetic_ruleset.py --api http://localhost:8010

Prints one line per schedule item (Part, status, template, rules, verified slots) and the
gaps, the calls and the cost. Exit code 1 when the job failed."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.check_synthetic_case import Api  # noqa: E402


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--key")
    parser.add_argument("--case", default="synthetic_tender")
    parser.add_argument("--project", help="reuse a project id instead of importing the case again")
    parser.add_argument("--timeout", type=float, default=1800.0)
    args = parser.parse_args()
    import requests

    api = Api(requests.Session(), args.api, args.key)
    if args.project:
        pid = args.project
    else:
        pid = api.call("POST", "/projects", json={"name": f"synthetic build {args.case}", "data_class": "synthetic"})["id"]
        imported = api.call("POST", f"/projects/{pid}/import", json={"path": args.case, "kind": "case"})
        log(f"project {pid}: {imported['tender_pdfs']} tender documents")
    job_id = api.call("POST", f"/projects/{pid}/ruleset/build", user="chenyu")["job_id"]
    log(f"build job {job_id}")
    started, last = time.time(), ""
    while True:
        job = api.call("GET", f"/projects/{pid}/jobs/{job_id}")
        line = f"  {job['state']} {job.get('step') or ''} {job.get('progress') or ''}"
        if line != last:
            log(line)
            last = line
        if job["state"] in ("done", "failed", "dead"):
            break
        if time.time() - started > args.timeout:
            log("timed out")
            return 1
        time.sleep(3)
    if job["state"] != "done":
        log(f"job {job['state']}: {job.get('error')}")
        return 1
    rs = api.call("GET", f"/projects/{pid}/ruleset")
    log(f"draft v{rs['version']} by {rs['created_by']} ({rs.get('model')}, {rs.get('prompt_version')}): "
        f"{len(rs['items'])} items, {len(rs['parts'])} Parts, {len(rs['gaps'])} gaps")
    print(f"{'item':4} {'part':4} {'status':12} {'template':26} {'rules':5} {'slots (verified/total)'}")
    for i in rs["items"]:
        slots = i["slots"]
        verified = sum(1 for s in slots.values() if s["verified"])
        print(f"({i['letter']}) {i['part']:4} {i['status']:12} {(i['template'] or '-'):26} {len(i['rules']):5} {verified}/{len(slots)}")
    for g in rs["gaps"][:12]:
        print(f"  gap {g['node_id']}: {g['text'][:90]}")
    if len(rs["gaps"]) > 12:
        print(f"  ... {len(rs['gaps']) - 12} more gaps")
    return 0


if __name__ == "__main__":
    sys.exit(main())

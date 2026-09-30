"""The Showcase: one synthetic case taken all the way to its reports through a running API, the
way two reviewers would, so a demo (and its recorded run, tools/record_run.py) shows every
window with real output.

    python tools/seed_showcase.py                                  # against http://localhost:8000
    python tools/seed_showcase.py --api https://host --key K --case synthetic_tender

The model does the reading: the rule set is drafted by the build job (L0 to L4) and every offer
is checked by the vendor check. The people are scripted, in the open: "showcase-builder" gives
the open gaps one reason and fills any required value the model missed, "showcase-approver"
confirms the rule set, and "showcase-reviewer" settles each check left to a person from the
case's answer key (ground_truth.json), then confirms each review. Every one of those steps
says so in its reason, and the reports list them. Synthetic cases only: the API refuses a
project that isn't."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
BUILDER, APPROVER, REVIEWER = "showcase-builder", "showcase-approver", "showcase-reviewer"
FROM_KEY = "from the synthetic case's answer key"
GAP_REASON = ("reviewed for the showcase: obligations on the Authority or during the contract, "
              "not requirements on what the tenderer submits")
# A value a template needs that the case's tender doesn't state: the builder sets it, and says so.
CASE_VALUES = {"synthetic_tender": {"tender_closing_date": ("2026-09-30", "the synthetic tender states no closing date; "
                                                                           "set for the showcase")}}


class Api:
    def __init__(self, base: str, key: str | None = None, session=None):
        import requests
        self.base, self.key, self.s = base.rstrip("/"), key, session or requests.Session()

    def call(self, method: str, path: str, user: str | None = None, **kw):
        headers = {**({"X-API-Key": self.key} if self.key else {}), **({"X-User": user} if user else {})}
        r = self.s.request(method, self.base + path, headers=headers, timeout=120, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else None

    def wait(self, pid: str, job_id: str, timeout: float, log) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.call("GET", f"/projects/{pid}/jobs/{job_id}")
            if job["state"] in ("done", "failed", "dead"):
                return job
            time.sleep(3)
        raise RuntimeError(f"job {job_id} still running after {timeout:.0f} s")


def review(check: dict, value: dict | None, letter: str, truth: dict) -> tuple[str, dict] | None:
    """What the reviewer does about one check that needs review, from the answer key:
    ("correct", body) when the model missed a value the page has, ("decide", body)
    otherwise; None to leave it (never happens for a needs_review check)."""
    field = check["field_id"].rsplit(".", 1)[-1]
    item = truth["items"].get(letter, {})
    if (value or {}).get("value") in (None, "") and field == "signature" and item.get("values", {}).get("signed"):
        page = item.get("page")
        return "correct", {"value": "signed", "reason": f"signed on page {page} ({FROM_KEY})"}
    if field == "rows_left_blank":
        return "decide", {"decision": "pass", "reason": f"every row of the schedule is filled in ({FROM_KEY})"}
    if letter == "i" and truth.get("manufacturer_itself"):
        return "decide", {"decision": "pass", "reason": f"the tenderer makes the goods itself, so no manufacturer's "
                                                        f"letter is needed ({FROM_KEY})"}
    if check["field_id"].startswith("documentary_evidence."):
        return "decide", {"decision": "dormant", "reason": "required only if the tender asks for it: left for the "
                                                           "Authority to ask (showcase)"}
    if check["field_id"] == "compliance_schedule.document":
        return "decide", {"decision": "pass", "reason": f"the Compliance Schedule is completed and marks every "
                                                        f"requirement as complied with ({FROM_KEY})"}
    return "decide", {"decision": "dormant", "reason": "left for the Authority to follow up (showcase)"}


def settle_inputs(api: Api, pid: str, case: str, truth: dict, log) -> None:
    """What confirmation still waits for, settled by the builder: a required value the model
    didn't find is set from the case (CASE_VALUES, or the answer key's estimated quantity), and a
    value it found but code couldn't verify on the page is confirmed as read. Each with a reason."""
    known = {**{k: v for k, v in CASE_VALUES.get(case, {}).items()},
             "estimated_quantity": (truth.get("estimated_quantity_kg"), FROM_KEY)}
    ruleset = api.call("GET", f"/projects/{pid}/ruleset")
    for item in ruleset["items"]:
        if item["status"] != "needs_input":
            continue
        for name, slot in item["slots"].items():
            if slot.get("value") in (None, "", []) and known.get(name, (None,))[0] is not None:
                value, why = known[name]
            elif slot.get("value") not in (None, "", []) and not slot.get("verified"):
                value, why = slot["value"], "confirmed as the model read it (showcase)"
            else:
                continue
            api.call("PATCH", f"/projects/{pid}/ruleset/items/{quote(item['letter'])}", user=BUILDER,
                     json={"slot": {"name": name, "value": value}, "reason": why})
            log(f"  ({item['letter']}) {name} = {value!r}: {why}")


def seed(api: Api, case: str, name: str, truth: dict, timeout: float = 1800.0, log=print) -> str:
    project = api.call("POST", "/projects", json={"name": name, "data_class": "synthetic"})
    pid = project["id"]
    got = api.call("POST", f"/projects/{pid}/import", json={"path": case})
    log(f"{pid}: {got['tender_pdfs']} tender documents, offers from {', '.join(sorted(got['bidders']))}")

    job = api.wait(pid, api.call("POST", f"/projects/{pid}/ruleset/build", user=BUILDER, json={})["job_id"], timeout, log)
    if job["state"] != "done":
        raise RuntimeError(f"the rule-set build {job['state']}: {job.get('error')}")
    draft = api.call("GET", f"/projects/{pid}/ruleset")
    open_gaps = [g for g in draft["gaps"] if not g.get("reason")]
    if open_gaps:
        draft["gaps"] = [{**g, "reason": g.get("reason") or GAP_REASON} for g in draft["gaps"]]
        body = {k: v for k, v in draft.items() if k not in ("status", "confirmed_by", "confirmed_at", "version", "project_id")}
        api.call("PUT", f"/projects/{pid}/ruleset/draft", user=BUILDER, json=body)
    log(f"rule set drafted: {len(draft['items'])} items; {len(open_gaps)} gaps given one reason")
    settle_inputs(api, pid, case, truth, log)
    confirmed = api.call("POST", f"/projects/{pid}/ruleset/confirm", user=APPROVER, json={})
    log(f"rule set v{confirmed['version']} confirmed by {confirmed['confirmed_by']}")

    for tenderer in sorted(truth["bids"]):          # one at a time: kind to a model's token limit
        job_id = api.call("POST", f"/projects/{pid}/checks", user=REVIEWER, json={"tenderers": [tenderer]})["job_ids"][tenderer]
        job = api.wait(pid, job_id, timeout, log)
        if job["state"] != "done":
            raise RuntimeError(f"the check of {tenderer} {job['state']}: {job.get('error')}")
        bid = truth["bids"][tenderer]
        result = api.call("GET", f"/projects/{pid}/bids/{tenderer}/results")
        settled = 0
        for _ in range(40):                          # each answer re-decides; take the next open check from it
            open_ = [(letter, c) for letter, v in sorted(result["verdicts"].items()) for c in v["checks"]
                     if c["status"] == "needs_review"]
            if not open_:
                break
            letter, check = open_[0]
            field = check["field_id"].rsplit(".", 1)[-1]
            kind, body = review(check, result["fields"].get(letter, {}).get(field), letter, bid)
            result = api.call("PATCH", f"/projects/{pid}/bids/{tenderer}/fields/{quote(letter)}/{quote(field)}",
                              user=REVIEWER, json=body)
            settled += 1
        api.call("POST", f"/projects/{pid}/bids/{tenderer}/review/confirm", user=REVIEWER, json={})
        log(f"  {tenderer}: Stage I {result['stage1']['outcome']}, Stage II {(result.get('stage2') or {}).get('outcome')}; "
            f"{settled} checks settled; review confirmed")
    return pid


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--key", default=None, help="X-API-Key, when the API has one")
    ap.add_argument("--case", default="synthetic_tender", help="an inbox case that carries a ground_truth.json")
    ap.add_argument("--name", default="Showcase: small tender, four offers")
    ap.add_argument("--truth", type=Path, default=None, help="default: test/data/<case>/ground_truth.json")
    args = ap.parse_args()
    truth = json.loads((args.truth or ROOT / "test" / "data" / args.case / "ground_truth.json").read_text())
    try:
        pid = seed(Api(args.api, args.key), args.case, args.name, truth)
    except RuntimeError as err:
        print(f"seed_showcase: {err}", file=sys.stderr)
        return 1
    print(f"Showcase ready: {pid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

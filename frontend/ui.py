"""Streamlit review UI for the Tender Evaluation Assistant.

Pure HTTP client of the backend API (BACKEND_URL) — no pipeline code or documents live
in this container. Flow: project -> upload documents -> derive & confirm rubric ->
evaluate -> review Stage I/II evidence -> download Word reports.
"""
from __future__ import annotations

import json
import os
import time

import requests
import streamlit as st

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("API_KEY", "")
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

st.set_page_config(page_title="Tender Evaluation Assistant", layout="wide")


def call(method: str, path: str, **kwargs):
    resp = requests.request(method, f"{BACKEND}{path}", headers=HEADERS, timeout=120, **kwargs)
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        raise RuntimeError(f"{method} {path} -> {resp.status_code}: {detail}")
    return resp


def wait_for_job(pid: str, placeholder) -> dict:
    """Poll the project status until the background job finishes."""
    while True:
        status = call("GET", f"/projects/{pid}/status").json()
        placeholder.info(f"⏳ {status.get('detail') or status['state']}")
        if status["state"] in ("done", "error", "idle"):
            return status
        time.sleep(2)


# ---------------------------------------------------------------- sidebar: project picker

st.sidebar.title("Tender Evaluation Assistant")
try:
    projects = call("GET", "/projects").json()
except Exception as err:
    st.sidebar.error(f"Backend not reachable at {BACKEND}\n\n{err}")
    st.stop()

names = {f"{p['name']} ({p['id']})": p["id"] for p in projects}
choice = st.sidebar.selectbox("Project", ["— create new —"] + list(names))
if choice == "— create new —":
    new_name = st.sidebar.text_input("New project name", placeholder="e.g. Tender 1")
    if st.sidebar.button("Create project", type="primary", disabled=not new_name):
        created = call("POST", "/projects", json={"name": new_name}).json()
        st.sidebar.success(f"Created {created['id']}")
        st.rerun()
    st.info("Create or select a project to begin.")
    st.stop()

pid = names[choice]
project = call("GET", f"/projects/{pid}").json()
st.sidebar.caption(
    f"Tender files: {len(project['tender_files'])} · Bidders: {len(project['bidders'])} · "
    f"Rubric: {'✓' if project['has_rubric'] else '—'} · "
    f"Evaluation: {'✓' if project['has_evaluation'] else '—'}")

with st.sidebar.expander("Danger zone"):
    sure = st.checkbox("Yes, delete this project and all its files", key="del_confirm")
    if st.button("Delete project", disabled=not sure):
        call("DELETE", f"/projects/{pid}")
        st.rerun()

tab_docs, tab_rubric, tab_eval, tab_reports = st.tabs(
    ["1 · Documents", "2 · Rubric (confirm)", "3 · Evaluation", "4 · Reports"])

# ---------------------------------------------------------------- 1: documents

with tab_docs:
    st.subheader("Import a whole case folder")
    st.caption("Drop a case folder into the server's `inbox/` directory "
               "(convention: `tender/*.pdf` + `bids/<tenderer>/*.pdf`), then import "
               "everything in one click. `demo_case` is pre-mounted.")
    inbox = call("GET", "/inbox").json()
    if inbox:
        labels = {f"{e['name']}  ({e['tender_pdfs']} tender PDFs, "
                  f"{len(e['bidders'])} bidders)": e["name"] for e in inbox}
        picked = st.selectbox("Inbox folder", list(labels))
        if st.button("Import case", type="primary"):
            result = call("POST", f"/projects/{pid}/import",
                          json={"path": labels[picked], "kind": "case"}).json()
            st.success(f"Imported {result['tender_pdfs']} tender PDFs and "
                       f"{len(result['bidders'])} bidders.")
            st.rerun()
    else:
        st.info("Inbox is empty — copy a case folder into `inbox/` on the server, "
                "or upload files manually below.")
    st.divider()
    left, right = st.columns(2)
    with left:
        st.subheader("Tender documents")
        st.caption(f"Uploaded: {', '.join(project['tender_files']) or 'none'}")
        tender_files = st.file_uploader("Add tender PDFs", type="pdf",
                                        accept_multiple_files=True, key="tender_up")
        if st.button("Upload tender documents", disabled=not tender_files):
            call("POST", f"/projects/{pid}/tender",
                 files=[("files", (f.name, f.getvalue(), "application/pdf")) for f in tender_files])
            st.rerun()
    with right:
        st.subheader("Bids (one tenderer at a time)")
        st.caption(f"Bidders so far: {', '.join(project['bidders']) or 'none'}")
        tenderer = st.text_input("Tenderer name", placeholder="e.g. Tenderer_A")
        bid_files = st.file_uploader("Offer PDFs", type="pdf",
                                     accept_multiple_files=True, key="bid_up")
        if st.button("Upload bid", disabled=not (tenderer and bid_files)):
            call("POST", f"/projects/{pid}/bids/{tenderer}",
                 files=[("files", (f.name, f.getvalue(), "application/pdf")) for f in bid_files])
            st.rerun()

# ---------------------------------------------------------------- 2: rubric checkpoint

with tab_rubric:
    st.subheader("Evaluation rubric — the human checkpoint")
    st.caption("Derived from the tender documents. Review and edit before evaluating: "
               "Stage I checklist, Stage II essential requirements, price scheme.")
    if st.button("Derive rubric from tender documents",
                 disabled=not project["tender_files"]):
        call("POST", f"/projects/{pid}/rubric/derive")
        result = wait_for_job(pid, st.empty())
        (st.error if result["state"] == "error" else st.success)(result["detail"])
        st.rerun()
    if project["has_rubric"]:
        rubric = call("GET", f"/projects/{pid}/rubric").json()
        edited = st.text_area("rubric.json (editable)",
                              json.dumps(rubric, indent=2, ensure_ascii=False), height=420)
        if st.button("Save rubric", type="primary"):
            try:
                call("PUT", f"/projects/{pid}/rubric", json=json.loads(edited))
                st.success("Rubric saved.")
            except (ValueError, RuntimeError) as err:
                st.error(f"Not saved: {err}")

# ---------------------------------------------------------------- 3: evaluation

with tab_eval:
    st.subheader("Run evaluation")
    st.caption("Extracts each bid (skipping ones already extracted/corrected), then runs "
               "the deterministic Stage I/II checks and price computation.")
    if st.button("Evaluate all bids", type="primary",
                 disabled=not (project["has_rubric"] and (project["bidders"] or project["extracted"]))):
        call("POST", f"/projects/{pid}/evaluate")
        result = wait_for_job(pid, st.empty())
        (st.error if result["state"] == "error" else st.success)(result["detail"])
        st.rerun()

    if project["has_evaluation"]:
        ev = call("GET", f"/projects/{pid}/evaluation").json()
        rubric = ev["rubric"]
        st.markdown(f"**{rubric['tender_ref']}** — {rubric['subject']}")
        if ev.get("recommended"):
            st.success(f"Recommended offer: **{ev['recommended']}**")

        st.markdown("#### Stage I — Completeness")
        items = [i["id"] for i in rubric["stage1_checklist"]]
        st.table([{"Tenderer": r["tenderer"],
                   **{i: ("✓" if r["presence"].get(i, {}).get("present") else "✗") for i in items},
                   "Result": "Pass" if r["passed"] else "Fail"} for r in ev["stage1"]])

        st.markdown("#### Stage II — Essential requirements")
        reqs = {q["id"]: q["requirement"] for q in rubric["stage2_requirements"]}
        for r in ev["stage2"]:
            with st.expander(f"{r['tenderer']} — {'Pass' if r['passed'] else 'Fail'}"):
                st.table([{"Requirement": f"{k}: {reqs.get(k, '')}",
                           "Finding": f["complies"],
                           "Evidence": f.get("evidence") or "—",
                           "Page": f.get("page") or "—"} for k, f in r["findings"].items()])

        st.markdown("#### Price summary")
        ce = rubric["price_scheme"]["type"] == "cost_effectiveness"
        st.table([{"Rank": r["ranking"] or "n/a", "Tenderer": r["tenderer"],
                   **({"Dosage (2 s.f.)": r["dosage_rounded"], "Cost-effectiveness": r["cost_effectiveness"]}
                      if ce else {"Unit price (HK$)": r["unit_price_hkd"],
                                  "Estimated goods price (HK$)": r["estimated_goods_price"]}),
                   "Conforming": "yes" if r["conforming"] else "no",
                   "Remark": r["remark"] or ""}
                  for r in sorted(ev["price_rows"], key=lambda x: (x["ranking"] is None, x["ranking"] or 0))])

# ---------------------------------------------------------------- 4: reports

with tab_reports:
    st.subheader("Word deliverables (editable)")
    reports = call("GET", f"/projects/{pid}/reports").json()
    if not reports:
        st.info("Run an evaluation first.")
    for name in reports:
        data = call("GET", f"/projects/{pid}/reports/{name}").content
        st.download_button(f"Download {name}", data, file_name=name,
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

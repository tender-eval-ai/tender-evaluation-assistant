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
import streamlit.components.v1 as components

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
# What the *browser* can reach (inside Docker, BACKEND_URL is the internal hostname).
PUBLIC_BACKEND = os.environ.get("PUBLIC_BACKEND_URL", BACKEND).rstrip("/")
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

FOLDER_PICKER_HTML = """
<style>
  body { font-family: -apple-system, "Segoe UI", sans-serif; margin: 0; }
  .box { border: 1px solid #d0d0d0; border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; }
  .box b { font-size: 0.95rem; }
  .hint { color: #666; font-size: 0.8rem; margin: 4px 0 8px 0; }
  .st { font-size: 0.85rem; margin-top: 8px; color: #444; min-height: 1.2em; }
  input[type=file] { font-size: 0.85rem; }
</style>
<div class="box">
  <b>Tender documents — choose a folder</b>
  <div class="hint">Every PDF inside (including subfolders) is uploaded as a tender document.</div>
  <input type="file" id="tin" webkitdirectory multiple>
  <div class="st" id="tst"></div>
</div>
<div class="box">
  <b>Bid documents — choose the folder that contains one subfolder per tenderer</b>
  <div class="hint">Each subfolder becomes one tenderer (its PDFs are collected recursively);
  loose PDFs directly inside become single-file tenderers.</div>
  <input type="file" id="bin" webkitdirectory multiple>
  <div class="st" id="bst"></div>
</div>
<script>
function pdfs(input) {
  return Array.from(input.files).filter(function (f) {
    return f.name.toLowerCase().endsWith('.pdf') && !f.name.startsWith('~$');
  });
}
function rel(f) { return f.webkitRelativePath || f.name; }
async function up(url, fd) {
  const r = await fetch(url, { method: 'POST', headers: HDRS, body: fd });
  if (!r.ok) { throw new Error(r.status + ' ' + (await r.text())); }
}
document.getElementById('tin').addEventListener('change', async function () {
  const el = document.getElementById('tst');
  const fs = pdfs(this);
  if (!fs.length) { el.textContent = 'No PDFs found in that folder.'; return; }
  el.textContent = 'Uploading ' + fs.length + ' PDFs...';
  const fd = new FormData();
  fs.forEach(function (f) {
    const parts = rel(f).split('/');
    fd.append('files', f, parts.length > 1 ? parts.slice(1).join('__') : f.name);
  });
  try {
    await up(B + '/projects/' + PID + '/tender', fd);
    el.textContent = 'Done: ' + fs.length + ' tender PDFs uploaded. Click Refresh below.';
  } catch (e) { el.textContent = 'Failed: ' + e.message; }
});
document.getElementById('bin').addEventListener('change', async function () {
  const el = document.getElementById('bst');
  const fs = pdfs(this);
  if (!fs.length) { el.textContent = 'No PDFs found in that folder.'; return; }
  const groups = {};
  fs.forEach(function (f) {
    const parts = rel(f).split('/');
    var tenderer, name;
    if (parts.length >= 3) { tenderer = parts[1]; name = parts.slice(2).join('__'); }
    else { tenderer = f.name.replace(/\\.pdf$/i, ''); name = f.name; }
    if (!groups[tenderer]) { groups[tenderer] = new FormData(); }
    groups[tenderer].append('files', f, name);
  });
  const names = Object.keys(groups);
  var done = 0;
  for (const t of names) {
    el.textContent = 'Uploading tenderer ' + (done + 1) + '/' + names.length + ': ' + t;
    try { await up(B + '/projects/' + PID + '/bids/' + encodeURIComponent(t), groups[t]); done++; }
    catch (e) { el.textContent = 'Failed at ' + t + ': ' + e.message; return; }
  }
  el.textContent = 'Done: ' + done + ' tenderer(s) uploaded. Click Refresh below.';
});
</script>
"""

with tab_docs:
    st.subheader("Upload by folder")
    st.caption(f"Tender files: {len(project['tender_files'])} · "
               f"Bidders: {', '.join(project['bidders']) or 'none'}")
    boot = ("<script>const B=" + json.dumps(PUBLIC_BACKEND) + ";const PID=" + json.dumps(pid)
            + ";const HDRS=" + json.dumps(HEADERS) + ";</script>")
    components.html(boot + FOLDER_PICKER_HTML, height=310)
    if st.button("↻ Refresh"):
        st.rerun()

    with st.expander("Import from server inbox (alternative)"):
        st.caption("Case folders placed in the server's `inbox/` directory "
                   "(`tender/*.pdf` + `bids/<tenderer>/*.pdf`). `demo_case` is pre-mounted.")
        inbox = call("GET", "/inbox").json()
        if inbox:
            labels = {f"{e['name']}  ({e['tender_pdfs']} tender PDFs, "
                      f"{len(e['bidders'])} bidders)": e["name"] for e in inbox}
            picked = st.selectbox("Inbox folder", list(labels))
            if st.button("Import case"):
                result = call("POST", f"/projects/{pid}/import",
                              json={"path": labels[picked], "kind": "case"}).json()
                st.success(f"Imported {result['tender_pdfs']} tender PDFs and "
                           f"{len(result['bidders'])} bidders.")
                st.rerun()
        else:
            st.info("Inbox is empty.")

    with st.expander("Manual file upload (fallback)"):
        left, right = st.columns(2)
        with left:
            tender_files = st.file_uploader("Tender PDFs", type="pdf",
                                            accept_multiple_files=True, key="tender_up")
            if st.button("Upload tender documents", disabled=not tender_files):
                call("POST", f"/projects/{pid}/tender",
                     files=[("files", (f.name, f.getvalue(), "application/pdf")) for f in tender_files])
                st.rerun()
        with right:
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

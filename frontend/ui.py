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

# Theme accent is blue (.streamlit/config.toml) — red is reserved for destructive
# actions, currently only the project-delete button.
st.markdown("""
<style>
.st-key-delete_project button:not(:disabled) {
  background: #d32f2f; border-color: #d32f2f; color: #fff;
}
.st-key-delete_project button:not(:disabled):hover,
.st-key-delete_project button:not(:disabled):active {
  background: #b71c1c; border-color: #b71c1c; color: #fff;
}
</style>
""", unsafe_allow_html=True)


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
    if st.button("Delete project", key="delete_project", disabled=not sure):
        call("DELETE", f"/projects/{pid}")
        st.rerun()

# A failed background job must stay visible across reruns, on every page.
if project["status"]["state"] == "error":
    st.error(f"Last job failed: {project['status']['detail']}")

# Segmented control instead of st.tabs: its selection survives st.rerun(), so
# finishing a job keeps the user on the page they were on.
NAV = ["1 · Documents", "2 · Rubric (confirm)", "3 · Extraction (review)",
       "4 · Evaluation", "5 · Reports"]
SHORT = [n.split(" · ")[1].split(" (")[0] for n in NAV]  # Documents, Rubric, ...


def _go(delta: int) -> None:
    """Button callback: runs before the rerun, when nav state may still be changed."""
    idx = NAV.index(st.session_state.get("nav_v2") or NAV[0])
    st.session_state["nav_v2"] = NAV[max(0, min(len(NAV) - 1, idx + delta))]


page = st.segmented_control("Navigation", NAV, key="nav_v2", default=NAV[0],
                            label_visibility="collapsed") or NAV[0]

# ---------------------------------------------------------------- 1: documents

FOLDER_PICKER_HTML = """
<style>
  body { font-family: -apple-system, "Segoe UI", sans-serif; margin: 0; color: #262730; }
  .card { border: 1px solid #d0d0d0; border-radius: 8px; margin-bottom: 16px; overflow: hidden; }
  .head { background: #1f6feb; color: #fff; font-size: 1.05rem; font-weight: 700;
          padding: 8px 14px; }
  .head .num { display: inline-block; background: #fff; color: #1f6feb; border-radius: 50%;
               width: 1.5em; height: 1.5em; line-height: 1.5em; text-align: center;
               font-size: 0.85em; margin-right: 8px; }
  .body { padding: 12px 14px; }
  .lead { font-weight: 600; margin: 0 0 2px 0; }
  .hint { color: #666; font-size: 0.8rem; margin: 0 0 8px 0; }
  .st { font-size: 0.85rem; margin-top: 8px; color: #444; min-height: 1.2em; }
  input[type=file] { font-size: 0.85rem; color: inherit; }
  @media (prefers-color-scheme: dark) {
    body { color: #fafafa; }
    .card { border-color: #555; }
    .hint { color: #b0b0b0; }
    .st { color: #d0d0d0; }
  }
</style>
<div class="card">
  <div class="head"><span class="num">1</span>Tender documents</div>
  <div class="body">
    <div class="lead">Choose a folder</div>
    <div class="hint">Every PDF inside (including subfolders) is uploaded as a tender document.</div>
    <input type="file" id="tin" webkitdirectory multiple>
    <div class="st" id="tst"></div>
  </div>
</div>
<div class="card">
  <div class="head"><span class="num">2</span>Bid documents</div>
  <div class="body">
    <div class="lead">Choose the folder that contains one subfolder per tenderer</div>
    <div class="hint">Each subfolder becomes one tenderer (its PDFs are collected recursively);
    loose PDFs directly inside become single-file tenderers.</div>
    <input type="file" id="bin" webkitdirectory multiple>
    <div class="st" id="bst"></div>
  </div>
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
    el.textContent = 'Done: ' + fs.length + ' tender PDFs uploaded. Counts above update in a few seconds.';
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
  el.textContent = 'Done: ' + done + ' tenderer(s) uploaded. Counts above update in a few seconds.';
});
</script>
"""

if page == NAV[0]:
    st.subheader("Upload by folder")

    @st.fragment(run_every="3s")
    def _live_counts():
        """Folder uploads go browser->backend directly, so Streamlit doesn't see them;
        poll the project and refresh the page when its contents change."""
        p = call("GET", f"/projects/{pid}").json()
        st.caption(f"Tender files: {len(p['tender_files'])} · "
                   f"Bidders: {', '.join(p['bidders']) or 'none'}")
        sig = (tuple(p["tender_files"]), tuple(p["bidders"]), tuple(p["extracted"]),
               p["has_rubric"], p["has_evaluation"], p["status"]["state"])
        key = f"proj_sig_{pid}"
        prev = st.session_state.get(key)
        st.session_state[key] = sig
        if prev is not None and prev != sig:
            st.rerun(scope="app")

    _live_counts()
    boot = ("<script>const B=" + json.dumps(PUBLIC_BACKEND) + ";const PID=" + json.dumps(pid)
            + ";const HDRS=" + json.dumps(HEADERS) + ";</script>")
    # Match the app's actual theme (like st.subheader does) instead of the OS
    # preference the iframe would otherwise follow; media query stays as fallback.
    try:
        dark = st.context.theme.type == "dark"
    except Exception:
        theme_css = ""
    else:
        theme_css = ("<style>body{color:#fafafa}.card{border-color:#555}"
                     ".hint{color:#b0b0b0}.st{color:#d0d0d0}</style>" if dark else
                     "<style>body{color:#31333f}.card{border-color:#d0d0d0}"
                     ".hint{color:#666}.st{color:#444}</style>")
    components.html(boot + FOLDER_PICKER_HTML + theme_css, height=360)

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

if page == NAV[1]:
    st.subheader("Evaluation rubric — the human checkpoint")
    st.caption("Derived from the tender documents. Review and edit before evaluating: "
               "Stage I checklist, Stage II essential requirements, price scheme.")
    if not project["tender_files"]:
        st.info("Upload tender documents first (Documents tab) to enable derivation.")
    if st.button("Derive rubric from tender documents",
                 disabled=not project["tender_files"]):
        call("POST", f"/projects/{pid}/rubric/derive")
        result = wait_for_job(pid, st.empty())
        if result["state"] == "error":
            st.error(result["detail"])  # stays on screen — no rerun on failure
        else:
            st.rerun()
    if project["has_rubric"]:
        rubric = call("GET", f"/projects/{pid}/rubric").json()

        def _cite(x: dict) -> str:
            bits = []
            if x.get("source_file"):
                bits.append(f"📄 {x['source_file']}")
            if x.get("source_page"):
                bits.append(f"p.{x['source_page']}")
            clause = (x.get("source_clause") or "").strip()
            if clause:
                bits.append("“" + (clause[:160] + "…" if len(clause) > 160 else clause) + "”")
            return " · ".join(bits)

        left, right = st.columns([3, 2])
        with left:
            st.markdown(f"**{rubric['tender_ref']}** — {rubric.get('subject') or ''}")
            st.markdown("##### Stage I — completeness checklist")
            for it in rubric["stage1_checklist"]:
                opt = "" if it.get("required", True) else " *(optional)*"
                st.markdown(f"`{it['id']}` {it['item']}{opt}")
                if _cite(it):
                    st.caption(_cite(it))
            st.markdown("##### Stage II — essential requirements")
            for rq in rubric["stage2_requirements"]:
                st.markdown(f"`{rq['id']}` {rq['requirement']}")
                if _cite(rq):
                    st.caption(_cite(rq))
            ps = rubric["price_scheme"]
            st.markdown("##### Price scheme")
            st.markdown(f"`{ps['type']}` — quantity {ps['quantity']} {ps.get('unit', '')}, "
                        f"{ps.get('currency', 'HKD')}"
                        + (f" — {ps['notes']}" if ps.get("notes") else ""))
            if _cite(ps):
                st.caption(_cite(ps))

        with right:
            st.markdown("**Source page preview**")
            cited = {}
            for x in (rubric["stage1_checklist"] + rubric["stage2_requirements"]
                      + [rubric["price_scheme"]]):
                if x.get("source_page"):
                    label = (f"{x.get('id', 'price scheme')} — "
                             f"{x.get('source_file') or 'tender'} p.{x['source_page']}")
                    cited[label] = x
            if cited:
                def _jump_rubric():
                    x = cited[st.session_state[f"rubric_ev_{pid}"]]
                    st.session_state[f"t_page_{pid}"] = int(x["source_page"])
                    if x.get("source_file") in project["tender_files"]:
                        st.session_state[f"t_file_{pid}"] = x["source_file"]
                st.selectbox("Jump to citation", list(cited), key=f"rubric_ev_{pid}",
                             on_change=_jump_rubric)
            else:
                st.caption("This rubric has no source citations — re-derive it to add them.")
            if project["tender_files"]:
                file_choice = st.selectbox("File", project["tender_files"], key=f"t_file_{pid}")
                page_no = st.number_input("Page", min_value=1, max_value=999,
                                          key=f"t_page_{pid}")
                img = requests.get(f"{BACKEND}/projects/{pid}/tender/page", headers=HEADERS,
                                   params={"page": int(page_no), "file": file_choice},
                                   timeout=60)
                if img.status_code == 200:
                    st.image(img.content, use_container_width=True)
                else:
                    st.info("Page not renderable — check the page number.")

        with st.expander("Edit rubric JSON (the checkpoint — save to confirm changes)"):
            edited = st.text_area("rubric.json", label_visibility="collapsed",
                                  value=json.dumps(rubric, indent=2, ensure_ascii=False),
                                  height=420)
            if st.button("Save rubric", type="primary"):
                try:
                    call("PUT", f"/projects/{pid}/rubric", json=json.loads(edited))
                    st.success("Rubric saved.")
                except (ValueError, RuntimeError) as err:
                    st.error(f"Not saved: {err}")

# ---------------------------------------------------------------- 3: evaluation

if page == NAV[2]:
    st.subheader("Extraction review — check the machine before it counts")
    st.caption("Extract every bid, then review and correct what the model read: "
               "document presence, compliance findings, price fields. Corrected bids "
               "are never re-extracted. Negative findings were already re-checked by "
               "an adversarial verification pass.")
    if st.button("Extract all bids", type="primary",
                 disabled=not (project["has_rubric"] and project["bidders"])):
        call("POST", f"/projects/{pid}/extract")
        result = wait_for_job(pid, st.empty())
        if result["state"] == "error":
            st.error(result["detail"])
        else:
            st.rerun()

    if not project["extracted"]:
        st.info("No extractions yet — run the extraction, or evaluate directly on the "
                "next page (it extracts anything missing).")
    else:
        tenderer = st.selectbox("Tenderer", project["extracted"])
        ext = call("GET", f"/projects/{pid}/bids/{tenderer}/extraction").json()
        docs_all, comp_all = ext["documents"], ext["compliance"]
        doc_issues = [r for r in docs_all if not r.get("present")]
        doc_passed = [r for r in docs_all if r.get("present")]
        comp_issues = [r for r in comp_all if r.get("complies") != "yes"]
        comp_passed = [r for r in comp_all if r.get("complies") == "yes"]

        COMP_COLS = {"complies": st.column_config.SelectboxColumn(
            "complies", options=["yes", "no", "unclear"], required=True)}
        STATUS_COL = {"status": st.column_config.TextColumn(" ", disabled=True,
                                                            width="small")}

        def _doc_status(r) -> str:
            return "🟢" if r.get("present") else "🔴"

        def _comp_status(r) -> str:
            return {"yes": "🟢", "no": "🔴"}.get(r.get("complies"), "🟠")

        def _editor(rows, status_of, tag, extra_cols=None):
            """data_editor with a read-only traffic-light column, stripped on return."""
            display = [{"status": status_of(r), **r} for r in rows]
            edited = st.data_editor(display, key=f"{tag}_{tenderer}", hide_index=True,
                                    use_container_width=True, num_rows="fixed",
                                    column_config={**STATUS_COL, **(extra_cols or {})})
            return [{k: v for k, v in r.items() if k != "status"} for r in edited]

        left, right = st.columns([3, 2])
        with left:
            n_issues = len(doc_issues) + len(comp_issues)
            if n_issues:
                st.markdown(f"##### ⚠️ Needs review — {n_issues} negative finding(s)")
            else:
                st.success("No negative findings for this tenderer.")
            doc_issues_e, comp_issues_e = doc_issues, comp_issues
            if doc_issues:
                st.markdown("**Documents flagged missing (Stage I)**")
                doc_issues_e = _editor(doc_issues, _doc_status, "docsi")
            if comp_issues:
                st.markdown("**Compliance flagged no / unclear (Stage II)**")
                comp_issues_e = _editor(comp_issues, _comp_status, "compi", COMP_COLS)

            doc_passed_e, comp_passed_e = doc_passed, comp_passed
            n_ok = len(doc_passed) + len(comp_passed)
            with st.expander(f"✅ Passed checks ({n_ok}) — show, verify, edit"):
                if doc_passed:
                    st.markdown("**Documents present (Stage I)**")
                    doc_passed_e = _editor(doc_passed, _doc_status, "docsp")
                if comp_passed:
                    st.markdown("**Compliant (Stage II)**")
                    comp_passed_e = _editor(comp_passed, _comp_status, "compp", COMP_COLS)

            st.markdown("**Price**")
            price = ext["price"]
            c1, c2, c3, c4 = st.columns(4)
            price["currency"] = c1.text_input("Currency", price.get("currency") or "HKD",
                                              key=f"cur_{tenderer}")
            price["unit_price"] = c2.number_input(
                "Unit price", value=float(price["unit_price"]) if price.get("unit_price")
                is not None else None, key=f"up_{tenderer}")
            price["optimal_dosage"] = c3.number_input(
                "Optimal dosage", value=float(price["optimal_dosage"])
                if price.get("optimal_dosage") is not None else None, key=f"od_{tenderer}")
            price["quoted_total"] = c4.number_input(
                "Quoted total", value=float(price["quoted_total"])
                if price.get("quoted_total") is not None else None, key=f"qt_{tenderer}")
            if st.button("Save corrections", type="primary", key=f"save_{tenderer}"):
                doc_order = {r["checklist_id"]: i for i, r in enumerate(docs_all)}
                comp_order = {r["requirement_id"]: i for i, r in enumerate(comp_all)}
                ext["documents"] = sorted(doc_issues_e + doc_passed_e,
                                          key=lambda r: doc_order.get(r["checklist_id"], 999))
                ext["compliance"] = sorted(comp_issues_e + comp_passed_e,
                                           key=lambda r: comp_order.get(r["requirement_id"], 999))
                ext["price"] = price
                call("PUT", f"/projects/{pid}/bids/{tenderer}/extraction", json=ext)
                st.success("Saved — this bid will not be re-extracted.")
        with right:
            st.markdown("**Evidence page preview**")
            cited = {}
            for r in doc_issues + doc_passed:
                if r.get("page"):
                    cited[f"{_doc_status(r)} {r['checklist_id']} — p.{r['page']}"] = int(r["page"])
            for r in comp_issues + comp_passed:
                if r.get("page"):
                    cited[f"{_comp_status(r)} {r['requirement_id']} — p.{r['page']}"] = int(r["page"])
            if cited:
                def _jump_bid():
                    st.session_state[f"page_{tenderer}"] = \
                        cited[st.session_state[f"ev_{tenderer}"]]
                st.selectbox("Jump to cited page", list(cited), key=f"ev_{tenderer}",
                             on_change=_jump_bid)
            files = [f.strip() for f in (ext.get("source_file") or "").split(",") if f.strip()]
            file_choice = st.selectbox("File", files, key=f"file_{tenderer}") if len(files) > 1 else None
            page_no = st.number_input("Page", min_value=1, max_value=999,
                                      key=f"page_{tenderer}")
            params = {"page": int(page_no)}
            if file_choice:
                params["file"] = file_choice
            img = requests.get(f"{BACKEND}/projects/{pid}/bids/{tenderer}/page",
                               headers=HEADERS, params=params, timeout=60)
            if img.status_code == 200:
                st.image(img.content, use_container_width=True)
            else:
                st.info("Page not renderable — check the page number.")

if page == NAV[3]:
    st.subheader("Run evaluation")
    st.caption("Extracts each bid (skipping ones already extracted/corrected), then runs "
               "the deterministic Stage I/II checks and price computation.")
    if st.button("Evaluate all bids", type="primary",
                 disabled=not (project["has_rubric"] and (project["bidders"] or project["extracted"]))):
        call("POST", f"/projects/{pid}/evaluate")
        result = wait_for_job(pid, st.empty())
        if result["state"] == "error":
            st.error(result["detail"])  # stays on screen — no rerun on failure
        else:
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

if page == NAV[4]:
    st.subheader("Word deliverables (editable)")
    reports = call("GET", f"/projects/{pid}/reports").json()
    if not reports:
        st.info("Run an evaluation first.")
    for name in reports:
        data = call("GET", f"/projects/{pid}/reports/{name}").content
        st.download_button(f"Download {name}", data, file_name=name,
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

# ---------------------------------------------------------------- back / next

st.divider()
idx = NAV.index(page)
back_col, _, next_col = st.columns([1, 3, 1])
with back_col:
    if idx > 0:
        st.button(f"← {SHORT[idx - 1]}", on_click=_go, args=(-1,),
                  use_container_width=True)
with next_col:
    if idx < len(NAV) - 1:
        st.button(f"{SHORT[idx + 1]} →", type="primary", on_click=_go, args=(1,),
                  use_container_width=True)

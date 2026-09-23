// MSW handlers for the S2 and S3 routes of docs/api_contract.md. The same handlers run
// in the browser (`npm run dev`, mock/browser.js) and in Vitest (mock/node.js).
// Paths start with `*` so they answer whatever VITE_API_BASE points at.
import { http, HttpResponse } from "msw";
import * as fx from "./fixtures.js";
import * as rs from "./rulesetStore.js";

// The routes this mock serves, as openapi.json names them. contract.test.js
// checks every one of them exists in the contract.
export const ROUTES = [
  ["get", "/projects"],
  ["get", "/projects/{pid}"],
  ["get", "/projects/{pid}/ruleset"],
  ["get", "/projects/{pid}/ruleset/versions"],
  ["put", "/projects/{pid}/ruleset/draft"],
  ["post", "/projects/{pid}/ruleset/confirm"],
  ["post", "/projects/{pid}/checks"],
  ["get", "/projects/{pid}/jobs"],
  ["get", "/projects/{pid}/jobs/{job_id}"],
  ["get", "/projects/{pid}/bids/{tenderer}/results"],
  ["get", "/projects/{pid}/documents"],
  ["get", "/projects/{pid}/documents/{doc_id}/pages"],
  ["get", "/projects/{pid}/documents/{doc_id}/pages/{n}/image"],
  ["get", "/projects/{pid}/events"],
  // The S3 editing routes reached openapi.json with PR #48 (S3-1).
  ["get", "/projects/{pid}/ruleset/diff"],
  ["get", "/projects/{pid}/ruleset/gaps"],
  ["post", "/projects/{pid}/ruleset/items"],
  ["patch", "/projects/{pid}/ruleset/items/{letter}"],
  ["delete", "/projects/{pid}/ruleset/items/{letter}"],
];

// The S3 rule-set routes of docs/api_contract.md that openapi.json does not
// have yet. contract.test.js checks their bodies against the models of
// app/rulesets/schema.py (mock/rulesetSchema.js) until it does.
export const S3_ROUTES = [
  // Empty since PR #48: every S3 route the mock serves is in openapi.json (see ROUTES).
];

// Mutable state: which tenderers have a finished check, and the jobs started
// through POST /checks. Tenderer_B starts unchecked so the Run check path
// (202 -> poll the job -> results) has something to do.
let state;
export function resetMockState() {
  state = { checked: new Set(["Tenderer_A", "Tenderer_C", "Tenderer_D"]), jobs: new Map(), nextJob: 1 };
  rs.resetRulesetStore();
}
resetMockState();

// {"error": {code, message, details}} plus `detail`, as backend/errors.py sends it.
function error(status, code, message, details = {}) {
  return HttpResponse.json({ error: { code, message, details }, detail: message }, { status });
}

// The acting user, as the API takes it until per-user sessions (B9).
const actingUser = (request) => request.headers.get("X-User") || "anonymous";

// A rulesetStore result as a response.
function reply(result) {
  if (result.error) return error(result.status, result.error.code, result.error.message, result.error.details);
  if (result.status === 204) return new HttpResponse(null, { status: 204 });
  return HttpResponse.json(result.body, { status: result.status });
}

const body = (request) => request.json().catch(() => null);

function projectOr404(pid) {
  return pid === fx.PID ? null : error(404, "not_found", `project '${pid}' not found`);
}

function escapeXml(s) {
  return s.replace(/[<>&"']/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;" })[c]);
}

// The page image. The real route renders the PDF page to PNG and, with
// `?highlight=<text>`, marks where that text is printed; the mock draws the
// same thing as SVG so no PDF renderer is needed in the browser or in Vitest.
// A scanned offer has no text layer, so nothing on it is marked.
export function pageSvg(docId, page, highlight) {
  const lines = fx.pageLines(docId, page);
  const doc = fx.findDocument(docId);
  const scanned = doc?.kind === "bid" && fx.TENDERERS[doc.tenderer].scanned;
  const needle = scanned ? "" : (highlight ?? "").trim().toLowerCase();
  const rows = lines
    .map((text, i) => {
      const y = fx.lineY(i);
      const size = i === 0 ? 20 : 15;
      const weight = i === 0 ? "bold" : "normal";
      // The quote within a line is marked where it is printed (the box a
      // PageCitation carries); a long quote wrapped over several lines marks
      // each of them whole.
      const line = text.toLowerCase();
      const at = needle ? line.indexOf(needle) : -1;
      const whole = needle && at < 0 && line.length >= 12 && needle.includes(line);
      const [x0, y0, x1, y1] = at >= 0 ? fx.lineBox(i, at, needle.length) : fx.lineBox(i, 0, text.length);
      const box =
        at >= 0 || whole
          ? `<rect data-highlight="true" x="${x0 - 4}" y="${y0 - 3}" width="${Math.min(535 - x0, x1 - x0 + 8)}" height="${y1 - y0 + 6}" fill="#fde047" fill-opacity="0.45" stroke="#ca8a04" stroke-width="2"/>`
          : "";
      return `${box}<text x="60" y="${y}" font-family="Georgia, serif" font-size="${size}" font-weight="${weight}" fill="#1f2937">${escapeXml(text)}</text>`;
    })
    .join("");
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="595" height="842" viewBox="0 0 595 842">` +
    `<rect width="595" height="842" fill="#ffffff"/>${rows}` +
    `<text x="297" y="810" text-anchor="middle" font-family="monospace" font-size="11" fill="#9ca3af">synthetic - page ${page}</text>` +
    `</svg>`
  );
}

export const handlers = [
  http.get("*/projects", () => HttpResponse.json([fx.project])),

  http.get("*/projects/:pid", ({ params }) => projectOr404(params.pid) ?? HttpResponse.json(fx.projectDetail())),

  http.get("*/projects/:pid/ruleset", ({ params, request }) => {
    const missing = projectOr404(params.pid);
    if (missing) return missing;
    const version = new URL(request.url).searchParams.get("version");
    return reply(rs.getRuleset(version == null ? null : Number(version)));
  }),

  http.get("*/projects/:pid/ruleset/versions", ({ params }) => projectOr404(params.pid) ?? reply(rs.listVersions())),

  http.get("*/projects/:pid/ruleset/diff", ({ params, request }) => {
    const missing = projectOr404(params.pid);
    if (missing) return missing;
    const q = new URL(request.url).searchParams;
    return reply(rs.diff(q.get("from"), q.get("to")));
  }),

  http.get("*/projects/:pid/ruleset/gaps", ({ params }) => projectOr404(params.pid) ?? reply(rs.listGaps())),

  http.patch("*/projects/:pid/ruleset/items/:letter", async ({ params, request }) =>
    projectOr404(params.pid) ?? reply(rs.patchItem(params.letter, await body(request), actingUser(request)))
  ),

  http.post("*/projects/:pid/ruleset/items", async ({ params, request }) =>
    projectOr404(params.pid) ?? reply(rs.addItem(await body(request), actingUser(request)))
  ),

  http.delete("*/projects/:pid/ruleset/items/:letter", async ({ params, request }) =>
    projectOr404(params.pid) ?? reply(rs.deleteItem(params.letter, await body(request), actingUser(request)))
  ),

  http.put("*/projects/:pid/ruleset/draft", async ({ params, request }) =>
    projectOr404(params.pid) ?? reply(rs.putDraft(await body(request), actingUser(request)))
  ),

  http.post("*/projects/:pid/ruleset/confirm", ({ params, request }) =>
    projectOr404(params.pid) ?? reply(rs.confirm(actingUser(request)))
  ),

  http.post("*/projects/:pid/checks", async ({ params, request }) => {
    const missing = projectOr404(params.pid);
    if (missing) return missing;
    const body = await request.json().catch(() => ({}));
    const tenderers = body?.tenderers ?? Object.keys(fx.TENDERERS);
    const unknown = tenderers.filter((t) => !fx.TENDERERS[t]);
    if (unknown.length) return error(404, "not_found", `no offer uploaded for ${unknown.join(", ")}`);
    const job_ids = {};
    for (const t of tenderers) {
      const running = [...state.jobs.values()].find((j) => j.tenderer === t && j.state === "running");
      if (running) return error(409, "conflict", `a check for ${t} is already running`, { job_id: running.job_id });
      const job_id = `job-${String(state.nextJob++).padStart(4, "0")}`;
      state.jobs.set(job_id, { job_id, tenderer: t, state: "running" });
      job_ids[t] = job_id;
    }
    return HttpResponse.json({ job_ids }, { status: 202 });
  }),

  http.get("*/projects/:pid/jobs", ({ params }) => {
    const missing = projectOr404(params.pid);
    if (missing) return missing;
    const items = [...state.jobs.values()].map((j) =>
      fx.job({ ...j, done: j.state === "done" ? 3 : 1 })
    );
    return HttpResponse.json({ items, next_cursor: null });
  }),

  // A job reports running once, then done: one poll in the UI sees progress,
  // the next sees the result.
  http.get("*/projects/:pid/jobs/:jobId", ({ params }) => {
    const missing = projectOr404(params.pid);
    if (missing) return missing;
    const j = state.jobs.get(params.jobId);
    if (!j) return error(404, "not_found", `job ${params.jobId} not found`);
    const body = fx.job({ ...j, done: j.state === "done" ? 3 : 1 });
    if (j.state === "running") {
      j.state = "done";
      state.checked.add(j.tenderer);
    }
    return HttpResponse.json(body);
  }),

  http.get("*/projects/:pid/bids/:tenderer/results", ({ params, request }) => {
    const missing = projectOr404(params.pid);
    if (missing) return missing;
    const t = params.tenderer;
    if (!fx.TENDERERS[t] || !state.checked.has(t)) {
      return error(404, "not_found", `no finished check for ${t} in ${params.pid}`);
    }
    const version = new URL(request.url).searchParams.get("version");
    if (version && Number(version) !== fx.RULESET_VERSION) {
      return error(404, "not_found", `${t}'s result is at rule-set version ${fx.RULESET_VERSION}, not ${version}`);
    }
    return HttpResponse.json(fx.bidResult(t));
  }),

  http.get("*/projects/:pid/documents", ({ params }) => projectOr404(params.pid) ?? HttpResponse.json(fx.documents())),

  http.get("*/projects/:pid/documents/:docId/pages", ({ params }) => {
    const missing = projectOr404(params.pid);
    if (missing) return missing;
    const pages = fx.pages(params.docId);
    return pages ? HttpResponse.json(pages) : error(404, "not_found", `document '${params.docId}' not found`);
  }),

  http.get("*/projects/:pid/documents/:docId/pages/:n/image", ({ params, request }) => {
    const missing = projectOr404(params.pid);
    if (missing) return missing;
    const doc = fx.findDocument(params.docId);
    if (!doc) return error(404, "not_found", `document '${params.docId}' not found`);
    const n = Number(params.n);
    if (!(n >= 1 && n <= doc.pages)) return error(404, "not_found", `page ${n} does not exist in ${doc.file}`);
    const url = new URL(request.url);
    const q = url.searchParams;
    if (!fx.verify(params.docId, n, q.get("exp"), q.get("sig"), q.get("highlight"))) {
      return error(403, "forbidden", "the image link is invalid or has expired");
    }
    return new HttpResponse(pageSvg(params.docId, n, url.searchParams.get("highlight")), {
      headers: { "Content-Type": "image/svg+xml" },
    });
  }),

  http.get("*/projects/:pid/events", ({ params }) =>
    projectOr404(params.pid) ?? HttpResponse.json({ items: [...fx.events, ...rs.events()], next_cursor: null })
  ),

  // Scoring and reports (S4). The two 409s are the ones the windows have to show
  // rather than swallow: no confirmed rule set, and a report asked for while a
  // review is still unconfirmed.
  http.get("*/projects/:pid/price-summary", ({ params }) =>
    projectOr404(params.pid) ?? HttpResponse.json(fx.priceSummary())),
  http.get("*/projects/:pid/evaluation", ({ params }) =>
    projectOr404(params.pid) ?? HttpResponse.json(fx.evaluation())),
  http.get("*/projects/:pid/reports", ({ params }) =>
    projectOr404(params.pid) ?? HttpResponse.json(fx.reports())),
];

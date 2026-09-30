// The S2 and S3 routes of docs/api_contract.md. Nothing here knows whether it talks
// to web/mock/ or to backend/: both answer the same shapes.
//
//   VITE_API_BASE  the API's origin, e.g. http://localhost:8000. Unset: the
//                  mock answers on the page's own origin.
//   VITE_API_MOCK  "1" or "0" forces the mock on or off (default: on exactly
//                  when VITE_API_BASE is unset).
//   VITE_API_KEY   sent as X-API-Key (development only: a key in a browser
//                  bundle is readable by anyone who loads the page).
//   VITE_API_USER  sent as X-User until per-user sessions arrive (B9).
//   VITE_REPLAY    "1": the guest site. Every GET is answered by a recorded run's static
//                  files under replay/ (tools/record_run.py); nothing can be changed.
//   VITE_REPLAY_LABEL  what the top bar says instead of "mock API", e.g. "Recorded run · 1 October 2026".
import { routeKey } from "./replayKey.js";

const env = import.meta.env ?? {};

export const REPLAY = env.VITE_REPLAY === "1";
export const REPLAY_LABEL = env.VITE_REPLAY_LABEL || "Recorded run";
export const USE_MOCK = !REPLAY && (env.VITE_API_MOCK ? env.VITE_API_MOCK === "1" : !env.VITE_API_BASE);
const replayRoot = () => `${env.BASE_URL ?? "/"}replay/`;
const RECORDED = "This is a recorded run: nothing here can be changed. Run it yourself to try it.";

// A GET from the recording: the exact path first, then without its query (a recording
// keeps a route once when every version answers the same). Anything else is refused.
async function replayed(method, path) {
  if (method !== "GET") throw new ApiError(405, "recorded_run", RECORDED);
  for (const candidate of new Set([path, path.split("?")[0]])) {
    const response = await fetch(`${replayRoot()}api/${routeKey(candidate)}`);
    if (response.ok) return response;
  }
  throw new ApiError(404, "not_found", `${path} is not in this recording`);
}

function apiBase() {
  const base = env.VITE_API_BASE || (typeof window !== "undefined" ? window.location.origin : "");
  return base.replace(/\/$/, "");
}

// A failed call, carrying the contract's error envelope
// {"error": {code, message, details}}.
export class ApiError extends Error {
  constructor(status, code, message, details = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

// The acting user, sent as X-User. On the mock the Rules window can switch it,
// so one browser can edit a draft as one person and confirm it as another.
let actingUser = env.VITE_API_USER || "";
export const getActingUser = () => actingUser || "anonymous";
export function setActingUser(name) {
  actingUser = (name ?? "").trim();
}

function headers(extra = {}) {
  const h = { ...extra };
  if (env.VITE_API_KEY) h["X-API-Key"] = env.VITE_API_KEY;
  if (actingUser) h["X-User"] = actingUser;
  return h;
}

// A call that answered 2xx, or an ApiError. `request` reads it as JSON; a report
// download reads it as a file.
async function call(method, path, body) {
  if (REPLAY) return replayed(method, path);
  const response = await fetch(`${apiBase()}${path}`, {
    method,
    headers: headers(body === undefined ? {} : { "Content-Type": "application/json" }),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return checked(response, method, path);
}

// Files as multipart/form-data; the browser sets the boundary and the length the API
// checks before it reads the body.
async function upload(path, files) {
  if (REPLAY) throw new ApiError(405, "recorded_run", RECORDED);
  const form = new FormData();
  for (const file of files) form.append("files", file, file.name);
  const response = await fetch(`${apiBase()}${path}`, { method: "POST", headers: headers(), body: form });
  return (await checked(response, "POST", path)).json();
}

async function checked(response, method, path) {
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const err = data.error ?? {};
    throw new ApiError(
      response.status,
      err.code ?? "error",
      err.message ?? `${method} ${path} failed: ${response.status}`,
      err.details ?? {}
    );
  }
  return response;
}

async function request(method, path, body) {
  const response = await call(method, path, body);
  return response.status === 204 ? null : response.json();
}

const q = (params) => {
  const s = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null)).toString();
  return s ? `?${s}` : "";
};
const p = (pid) => `/projects/${encodeURIComponent(pid)}`;

// Projects (today's routes, kept).
export const listProjects = () => request("GET", "/projects");
export const getProject = (pid) => request("GET", p(pid));
// The front door (#132): what this deployment allows, the prepared cases, a new project.
export const getSettings = () => request("GET", "/settings");
export const listInbox = () => request("GET", "/inbox");
export const createProject = (name, dataClass) => request("POST", "/projects", { name, data_class: dataClass });
export const importCase = (pid, path) => request("POST", `${p(pid)}/import`, { path });
export const uploadTender = (pid, files) => upload(`${p(pid)}/tender`, files);
export const uploadBid = (pid, tenderer, files) => upload(`${p(pid)}/bids/${encodeURIComponent(tenderer)}`, files);
export const buildRuleset = (pid) => request("POST", `${p(pid)}/ruleset/build`, {});

// Rules window.
export const getRuleset = (pid, { version } = {}) => request("GET", `${p(pid)}/ruleset${q({ version })}`);
export const listRulesetVersions = (pid) => request("GET", `${p(pid)}/ruleset/versions`);
export const confirmRuleset = (pid) => request("POST", `${p(pid)}/ruleset/confirm`, {});
export const getRulesetDiff = (pid, from, to) => request("GET", `${p(pid)}/ruleset/diff${q({ from, to })}`);
export const listRulesetGaps = (pid) => request("GET", `${p(pid)}/ruleset/gaps`);
// ItemPatch {slot?: {name, value}, rule?, template?, note?, reason}
export const patchRulesetItem = (pid, letter, patch) =>
  request("PATCH", `${p(pid)}/ruleset/items/${encodeURIComponent(letter)}`, patch);
// NewItem {title, part, citation, rules, reason}
export const addRulesetItem = (pid, item) => request("POST", `${p(pid)}/ruleset/items`, item);
export const deleteRulesetItem = (pid, letter, reason) =>
  request("DELETE", `${p(pid)}/ruleset/items/${encodeURIComponent(letter)}`, { reason });
export const putRulesetDraft = (pid, draft) => request("PUT", `${p(pid)}/ruleset/draft`, draft);

// Stage I and II window. POST /checks always runs against the latest
// confirmed rule set; 409 unconfirmed_ruleset when there is none.
export const startChecks = (pid, tenderers) =>
  request("POST", `${p(pid)}/checks`, tenderers ? { tenderers } : {});
export const getJob = (pid, jobId) => request("GET", `${p(pid)}/jobs/${encodeURIComponent(jobId)}`);
export const listJobs = (pid) => request("GET", `${p(pid)}/jobs`);
export const getBidResult = (pid, tenderer, { version } = {}) =>
  request("GET", `${p(pid)}/bids/${encodeURIComponent(tenderer)}/results${q({ version })}`);

// Document viewer.
export const listDocuments = (pid) => request("GET", `${p(pid)}/documents`);
export const listPages = (pid, docId) => request("GET", `${p(pid)}/documents/${encodeURIComponent(docId)}/pages`);

// Audit.
export const listEvents = (pid, params = {}) => request("GET", `${p(pid)}/events${q(params)}`);

// Scoring and reports (S4). Every one is pinned to a rule-set version: omit it for
// the latest confirmed. `price-summary` and `evaluation` answer 409
// `unconfirmed_ruleset` before a rule set is confirmed, and a report answers 409
// `review_pending` with `details.tenderers` while any checked review is unconfirmed -
// both are ApiError, so a window shows the reason rather than an empty table.
export const getPriceSummary = (pid, { version } = {}) =>
  request("GET", `${p(pid)}/price-summary${q({ version })}`);
export const getEvaluation = (pid, { version } = {}) =>
  request("GET", `${p(pid)}/evaluation${q({ version })}`);
export const listReports = (pid, { version } = {}) =>
  request("GET", `${p(pid)}/reports${q({ version })}`);

// A report is a .docx, not JSON. It is fetched like every other call, because the
// reports route requires the X-API-Key header and a plain link cannot send one, and
// handed back as a Blob with the name the API gives it, for the window to save. A
// refusal is an ApiError like any other: 409 `review_pending` names the tenderers
// still open in `details.tenderers`.
export async function downloadReport(pid, name, { version } = {}) {
  const response = await call("GET", `${p(pid)}/reports/${encodeURIComponent(name)}${q({ version })}`);
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? name;
  return { blob: await response.blob(), filename };
}

// Review (S4). A correction keeps the model's value beside the person's and the
// engine re-decides the verdict at once, with no model call; `reason` is required and
// an empty request is a 400. Confirming answers 409 `conflict` with `details.fields`
// while any checked field is still needs_review, so the caller can say which.
export const correctField = (pid, tenderer, letter, field, correction) =>
  request("PATCH", `${p(pid)}/bids/${encodeURIComponent(tenderer)}/fields/`
    + `${encodeURIComponent(letter)}/${encodeURIComponent(field)}`, correction);

export const confirmReview = (pid, tenderer) =>
  request("POST", `${p(pid)}/bids/${encodeURIComponent(tenderer)}/review/confirm`, {});

// Re-evaluate every checked tenderer against a confirmed rule-set version (default:
// the latest confirmed), as a job of kind `evaluate`. Engine only, no model call.
// A result whose verdict changed loses its review confirmation, which is why this is
// offered after confirming a version rather than run automatically.
export const reevaluate = (pid, { version } = {}) =>
  request("POST", `${p(pid)}/evaluate`, version == null ? {} : { version });

// Page images: `image_url` in a PageCitation or Page is a signed link relative
// to the API. The browser opens it as a plain <img>, so no key is attached.
// A PageCitation's link is used as given: its highlight is inside the
// signature. `highlight` is only for a page-only link (Page.image_url), where
// the Rules window marks a rule set quote on a tender page; the API still
// accepts that unsigned highlight until tender citations are signed (S3).
export function pageImageUrl(imageUrl, { highlight } = {}) {
  if (REPLAY) {
    const recorded = new URL(imageUrl, "http://replay.invalid/");
    if (highlight) recorded.searchParams.set("highlight", highlight);
    return `${replayRoot()}img/${routeKey(recorded.pathname + recorded.search)}.jpg`;
  }
  const url = new URL(imageUrl, `${apiBase()}/`);
  if (highlight) url.searchParams.set("highlight", highlight);
  return url.toString();
}

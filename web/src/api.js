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
const env = import.meta.env ?? {};

export const USE_MOCK = env.VITE_API_MOCK ? env.VITE_API_MOCK === "1" : !env.VITE_API_BASE;

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

async function request(method, path, body) {
  const response = await fetch(`${apiBase()}${path}`, {
    method,
    headers: headers(body === undefined ? {} : { "Content-Type": "application/json" }),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const err = data.error ?? {};
    throw new ApiError(
      response.status,
      err.code ?? "error",
      err.message ?? data.detail ?? `${method} ${path} failed: ${response.status}`,
      err.details ?? {}
    );
  }
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

// Review (S4). A correction keeps the model's value beside the person's and the
// engine re-decides the verdict at once, with no model call; `reason` is required and
// an empty request is a 400. Confirming answers 409 `conflict` with `details.fields`
// while any checked field is still needs_review, so the caller can say which.
export const correctField = (pid, tenderer, letter, field, correction) =>
  request("PATCH", `${p(pid)}/bids/${encodeURIComponent(tenderer)}/fields/`
    + `${encodeURIComponent(letter)}/${encodeURIComponent(field)}`, correction);

export const confirmReview = (pid, tenderer) =>
  request("POST", `${p(pid)}/bids/${encodeURIComponent(tenderer)}/review/confirm`, {});

// Page images: `image_url` in a PageCitation or Page is a signed link relative
// to the API. The browser opens it as a plain <img>, so no key is attached.
// A PageCitation's link is used as given: its highlight is inside the
// signature. `highlight` is only for a page-only link (Page.image_url), where
// the Rules window marks a rule set quote on a tender page; the API still
// accepts that unsigned highlight until tender citations are signed (S3).
export function pageImageUrl(imageUrl, { highlight } = {}) {
  const url = new URL(imageUrl, `${apiBase()}/`);
  if (highlight) url.searchParams.set("highlight", highlight);
  return url.toString();
}

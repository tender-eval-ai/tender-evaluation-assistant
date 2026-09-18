const API_BASE = "http://localhost:8421";

async function getJSON(path) {
  const response = await fetch(`${API_BASE}${path}`, { credentials: "include" });
  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status}`);
  }
  return response.json();
}

export async function login(username, password) {
  const response = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `login failed: ${response.status}`);
  }
  return data;
}

export async function logout() {
  await fetch(`${API_BASE}/api/auth/logout`, { method: "POST", credentials: "include" });
}

export async function getCurrentUser() {
  const response = await fetch(`${API_BASE}/api/auth/me`, { credentials: "include" });
  if (!response.ok) {
    return null;
  }
  return response.json();
}

export function listTenders() {
  return getJSON("/api/tenders");
}

export function getStage1Requirements(tenderId, { refresh = false } = {}) {
  const query = refresh ? "?refresh=1" : "";
  return getJSON(`/api/tenders/${tenderId}/stage1/requirements${query}`);
}

export function stage1RtmCsvUrl(tenderId) {
  return `${API_BASE}/api/tenders/${tenderId}/stage1/rtm.csv`;
}

export function getStage1Rtm(tenderId) {
  return getJSON(`/api/tenders/${tenderId}/stage1/rtm`);
}

export function getRequirementsConfirmation(tenderId) {
  return getJSON(`/api/tenders/${tenderId}/stage1/rtm/confirmation`);
}

export function postConfirmAllRequirements(tenderId) {
  return fetch(`${API_BASE}/api/tenders/${tenderId}/stage1/rtm/confirm-all`, {
    method: "POST",
    credentials: "include",
  }).then((response) => {
    if (!response.ok) throw new Error(`Confirm-all failed (${response.status})`);
    return response.json();
  });
}

export function postStage1Decision(tenderId, reqKey, { status, notes, summary }) {
  return fetch(`${API_BASE}/api/tenders/${tenderId}/stage1/rtm/${encodeURIComponent(reqKey)}/decision`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, notes, summary }),
  }).then((response) => {
    if (!response.ok) throw new Error(`Decision failed (${response.status})`);
    return response.json();
  });
}

export function getStage1ItemSummaries(tenderId) {
  // Separate from the checklist on purpose: the checklist is a deterministic
  // parse, these labels are model-generated. Failure returns {} and the UI falls
  // back to verbatim text rather than blocking the panel.
  return getJSON(`/api/tenders/${tenderId}/stage1/summaries`).catch(() => ({}));
}

export function getStage1CompletenessChecklist(tenderId, { refresh = false } = {}) {
  const query = refresh ? "?refresh=1" : "";
  return getJSON(`/api/tenders/${tenderId}/stage1/completeness-checklist${query}`);
}

export function getStage1SourcePage(tenderId) {
  return getJSON(`/api/tenders/${tenderId}/stage1/source-page`);
}

// Landing page for the Completeness Check step, one row per real vendor -
// cache-only rollup (see get_vendor_completeness_summary), never triggers a
// check itself just from being viewed.
export function getStage1VendorSummary(tenderId) {
  return getJSON(`/api/tenders/${tenderId}/stage1/vendors`);
}

// One click, every registered vendor run through the check pipeline in turn
// (server-side, sequential - see batch_jobs.py). Same start/poll shape as
// startStage1VendorCheck/getStage1VendorCheckStatus, one level up (per
// tender, not per vendor).
export function startStage1VendorCheckAll(tenderId, { refresh = false } = {}) {
  const query = refresh ? "?refresh=1" : "";
  return fetch(`${API_BASE}/api/tenders/${tenderId}/stage1/vendors/check-all/start${query}`, {
    method: "POST",
    credentials: "include",
  }).then((response) => response.json());
}

export function getStage1VendorCheckAllStatus(tenderId) {
  return getJSON(`/api/tenders/${tenderId}/stage1/vendors/check-all/status`);
}

export function startStage1VendorCheck(tenderId, vendorId, { refresh = false } = {}) {
  const query = refresh ? "?refresh=1" : "";
  return fetch(`${API_BASE}/api/tenders/${tenderId}/vendors/${vendorId}/stage1/check/start${query}`, {
    method: "POST",
    credentials: "include",
  }).then((response) => response.json());
}

export function getStage1VendorCheckStatus(tenderId, vendorId) {
  return getJSON(`/api/tenders/${tenderId}/vendors/${vendorId}/stage1/check/status`);
}

// Reviewer decisions (confirm/reject/flag) on individual RULES-panel fields -
// separate from the checker's own computed status, same relationship as the
// Requirements tab's RTM decision sits alongside a parsed requirement.
export function getVendorFieldReviews(tenderId, vendorId) {
  return getJSON(`/api/tenders/${tenderId}/vendors/${vendorId}/stage1/fields/reviews`);
}

export function postVendorFieldDecision(tenderId, vendorId, letter, fieldId, { decision, note, computedStatus }) {
  return fetch(
    `${API_BASE}/api/tenders/${tenderId}/vendors/${vendorId}/stage1/fields/${letter}/${encodeURIComponent(fieldId)}/decision`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, note, computed_status: computedStatus }),
    }
  ).then((response) => {
    if (!response.ok) throw new Error(`Field decision failed (${response.status})`);
    return response.json();
  });
}

export function listTenderPages(tenderId) {
  return getJSON(`/api/tenders/${tenderId}/pages`);
}

export function listVendorPages(vendorId) {
  return getJSON(`/api/vendors/${vendorId}/pages`);
}

export function tenderDocumentPageImageUrl(tenderId, docName, pageNumber, { thumb = false } = {}) {
  const query = thumb ? "?thumb=1" : "";
  return `${API_BASE}/api/tenders/${tenderId}/documents/${encodeURIComponent(docName)}/pages/${pageNumber}/image${query}`;
}

export function vendorPageImageUrl(vendorId, docName, pageNumber, { thumb = false } = {}) {
  const query = thumb ? "?thumb=1" : "";
  return `${API_BASE}/api/vendors/${vendorId}/documents/${encodeURIComponent(docName)}/pages/${pageNumber}/image${query}`;
}

// Status-label copy is fetched once and cached in-module - it's static per
// backend process (field_result.STATUS_LABELS), not per-tender/vendor data.
let statusLabelsPromise = null;
export function getValidatorStatusLabels() {
  if (!statusLabelsPromise) {
    statusLabelsPromise = getJSON("/api/validator/status-labels").catch((err) => {
      statusLabelsPromise = null;
      throw err;
    });
  }
  return statusLabelsPromise;
}

export function getStage3PriceSummary(tenderId) {
  return getJSON(`/api/tenders/${tenderId}/stage3/price-summary`);
}

export function getReport(tenderId) {
  return getJSON(`/api/tenders/${tenderId}/report`);
}

// POST, not GET: explicit-button action (can run a checker against freshly
// supplied data), and a GET request can't carry the optional `item` body a
// browser's fetch() needs to send here.
export function postStage1Validation(tenderId, vendorId, letter, item = null) {
  return fetch(`${API_BASE}/api/tenders/${tenderId}/vendors/${vendorId}/stage1/checklist/${letter}/validation`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(item ? { item } : {}),
  }).then((response) => {
    if (!response.ok) throw new Error(`Validation check failed (${response.status})`);
    return response.json();
  });
}

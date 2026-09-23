// The mock's rule sets: an in-memory list of versions that behaves as
// docs/api_contract.md describes the S3 rule-set routes.
//
//   v1  confirmed  fixtures/ruleset.json        (a), (k), (l)
//   v2  draft      fixtures/ruleset_draft.json  adds (c) Price Schedule, which
//                  needs input, edits a rule note of (k), and carries two gaps,
//                  one without a reason: v2 cannot be confirmed as it stands.
//
// Every human change is an attributed record: {by, at, reason} on the item
// (and on a corrected slot, whose `model_value` keeps what the model said).
// The last editor of a draft cannot confirm it (403 self_approval).
import confirmedV1 from "./fixtures/ruleset.json";
import draftV2 from "./fixtures/ruleset_draft.json";
import { validateItem, validateItemPatch, validateNewItem, validateRuleSet } from "./rulesetSchema.js";

const clone = (v) => structuredClone(v);
const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, "Z");

let state;
export function resetRulesetStore() {
  state = {
    // version -> {spec: RuleSet, updatedBy: who last changed it}
    versions: [
      { spec: clone(confirmedV1), updatedBy: confirmedV1.created_by },
      { spec: clone(draftV2), updatedBy: "chenyu" },
    ],
    events: [],
  };
}
resetRulesetStore();

// A result the handlers turn into a response: {status, body} or
// {status, error: {code, message, details}}.
const ok = (body, status = 200) => ({ status, body });
const fail = (status, code, message, details = {}) => ({ status, error: { code, message, details } });

export const latest = () => state.versions.at(-1).spec;
const draftEntry = () => {
  const last = state.versions.at(-1);
  return last.spec.status === "draft" ? last : null;
};
const findVersion = (n) => state.versions.find((v) => v.spec.version === n)?.spec ?? null;

// Only a confirmed version can be evaluated against - a draft has not been agreed,
// which is the whole point of the confirm step.
export const isConfirmed = (version) =>
  state.versions.some(({ spec }) => spec.version === Number(version) && spec.status === "confirmed");


export function getRuleset(version) {
  if (version == null) return ok(clone(latest()));
  const spec = findVersion(version);
  return spec ? ok(clone(spec)) : fail(404, "not_found", `rule set version ${version} does not exist`);
}

// RuleSetVersion as openapi.json has it: date-time strings, no updated_by. The
// store already keeps them as ISO, so they pass straight through; `seconds()`
// was written against the S2 snapshot, when the contract had floats here.
export function listVersions() {
  return ok(
    state.versions.map(({ spec }) => ({
      version: spec.version,
      status: spec.status,
      parent_version: spec.parent_version,
      created_by: spec.created_by,
      created_at: spec.created_at,
      confirmed_by: spec.confirmed_by,
      confirmed_at: spec.confirmed_at,
    }))
  );
}

export function listGaps() {
  return ok(clone(latest().gaps));
}

export function events() {
  return state.events;
}

let eventId = 100;
function record(kind, subject, before, after, user, reason) {
  state.events.push({
    id: eventId++,
    kind,
    project: latest().project_id,
    subject,
    before,
    after,
    user,
    reason,
    at: nowIso(),
  });
}

// Editing a confirmed set opens a new draft whose parent is the confirmed one.
function ensureDraft(user) {
  const open = draftEntry();
  if (open) return open;
  const parent = latest();
  const entry = {
    spec: {
      ...clone(parent),
      version: parent.version + 1,
      parent_version: parent.version,
      status: "draft",
      created_by: user,
      created_at: nowIso(),
      confirmed_by: null,
      confirmed_at: null,
    },
    updatedBy: user,
  };
  state.versions.push(entry);
  return entry;
}

const invalid = (errors, message = "the request does not validate") =>
  fail(422, "validation_failed", message, { errors });

// TemplateRule as pydantic dumps it: every field present, defaults filled.
function withRuleDefaults(rule) {
  return {
    params: {},
    consequence: null,
    normalise: [],
    stage: "I",
    condition: null,
    depends_on: [],
    note: null,
    ...rule,
    outcomes: rule.outcomes
      ? Object.fromEntries(Object.entries(rule.outcomes).map(([k, o]) => [k, { note: null, follow_up: null, ...o }]))
      : null,
  };
}

// PATCH /ruleset/items/{letter}: a slot value, a rule, the template or a note.
export function patchItem(letter, patch, user) {
  const errors = validateItemPatch(patch);
  if (errors.length) return invalid(errors);
  const current = draftEntry()?.spec ?? latest();
  if (!current.items.some((i) => i.letter === letter)) {
    return fail(404, "not_found", `the rule set has no item (${letter})`);
  }
  const edit = { by: user, at: nowIso(), reason: patch.reason.trim() };
  const item = clone(current.items.find((i) => i.letter === letter));
  const before = clone(item);

  if (patch.slot) {
    const slot = item.slots[patch.slot.name];
    if (!slot) return invalid([{ loc: ["slot", "name"], msg: `item (${letter}) has no slot '${patch.slot.name}'`, type: "value_error" }]);
    item.slots[patch.slot.name] = {
      ...slot,
      value: patch.slot.value,
      verified: false,
      origin: "manual",
      // The model's value stays beside the correction; a second correction
      // keeps the model's, not the first person's.
      model_value: slot.origin === "manual" ? slot.model_value : slot.value,
      edit,
    };
  }
  if (patch.rule) {
    const rule = withRuleDefaults(patch.rule);
    const at = item.rules.findIndex((r) => r.id === rule.id);
    if (at >= 0) item.rules[at] = rule;
    else item.rules.push(rule);
  }
  if ("template" in patch) item.template = patch.template ? patch.template : null;
  if (patch.note) item.notes.push({ kind: "reference", text: patch.note, citation: null });
  item.status = "edited";
  item.edit = edit;

  const itemErrors = validateItem(item);
  if (itemErrors.length) return invalid(itemErrors, `item (${letter}) does not validate after the change`);

  const entry = ensureDraft(user);
  entry.spec.items = entry.spec.items.map((i) => (i.letter === letter ? item : i));
  entry.updatedBy = user;
  record("ruleset.item_edited", `v${entry.spec.version}:${letter}`, before, item, user, edit.reason);
  return ok(clone(item));
}

// POST /ruleset/items: an item from clause text selected in the viewer. A
// person adds it, so it is `edited` with the edit record; letters x1, x2, ...
export function addItem(body, user) {
  const errors = validateNewItem(body);
  if (errors.length) return invalid(errors);
  const current = draftEntry()?.spec ?? latest();
  const used = current.items.map((i) => /^x(\d+)$/.exec(i.letter)?.[1]).filter(Boolean).map(Number);
  const letter = `x${Math.max(0, ...used) + 1}`;
  const edit = { by: user, at: nowIso(), reason: body.reason.trim() };
  const item = {
    letter,
    title: body.title,
    part: body.part,
    template: null,
    citation: { node_id: null, ...body.citation },
    clauses: [],
    condition: null,
    notes: [],
    slots: {},
    rules: body.rules.map(withRuleDefaults),
    status: "edited",
    edit,
  };
  const itemErrors = validateItem(item);
  if (itemErrors.length) return invalid(itemErrors, `the new item does not validate`);
  const entry = ensureDraft(user);
  entry.spec.items.push(item);
  entry.updatedBy = user;
  record("ruleset.item_added", `v${entry.spec.version}:${letter}`, null, item, user, edit.reason);
  return ok(clone(item));
}

export function deleteItem(letter, body, user) {
  const reason = typeof body?.reason === "string" ? body.reason.trim() : "";
  if (!reason) return invalid([{ loc: ["reason"], msg: "Field required", type: "missing" }], "a reason is required");
  const current = draftEntry()?.spec ?? latest();
  const item = current.items.find((i) => i.letter === letter);
  if (!item) return fail(404, "not_found", `the rule set has no item (${letter})`);
  const entry = ensureDraft(user);
  entry.spec.items = entry.spec.items.filter((i) => i.letter !== letter);
  entry.updatedBy = user;
  record("ruleset.item_deleted", `v${entry.spec.version}:${letter}`, clone(item), null, user, reason);
  return { status: 204 };
}

// PUT /ruleset/draft: the whole draft; the server owns version, status and
// the audit fields, as backend/routes/rulesets.py does.
export function putDraft(body, user) {
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    return invalid([{ loc: [], msg: "Input should be a valid dictionary", type: "dict_type" }], "the rule set does not validate");
  }
  const open = draftEntry();
  const base = latest();
  const version = open ? base.version : base.version + 1;
  const candidate = {
    ...body,
    project_id: base.project_id,
    version,
    parent_version: open ? base.parent_version : base.version,
    status: "draft",
    confirmed_by: null,
    confirmed_at: null,
    created_by: body.created_by ?? user,
    created_at: body.created_at ?? nowIso(),
  };
  const errors = validateRuleSet(candidate);
  if (errors.length) return invalid(errors, "the rule set does not validate");
  const before = open ? clone(open.spec) : null;
  if (open) {
    open.spec = candidate;
    open.updatedBy = user;
  } else {
    state.versions.push({ spec: candidate, updatedBy: user });
  }
  record("ruleset.draft_saved", `v${version}`, before, clone(candidate), user, open ? "draft replaced" : "new draft");
  return ok(clone(candidate));
}

export function confirm(user) {
  const open = draftEntry();
  if (!open) return fail(409, "conflict", "there is no draft to confirm");
  const { spec } = open;
  if (open.updatedBy === user) {
    return fail(403, "self_approval", `${user} last edited draft v${spec.version}; another person must confirm it`, {
      editor: user,
      version: spec.version,
    });
  }
  const confirmed = { ...clone(spec), status: "confirmed", confirmed_by: user, confirmed_at: nowIso() };
  const errors = validateRuleSet(confirmed);
  if (errors.length) return fail(409, "conflict", "the draft cannot be confirmed yet", { errors });
  open.spec = confirmed;
  record("ruleset.confirmed", `v${spec.version}`, clone(spec), clone(confirmed), user, null);
  return ok(clone(confirmed));
}

// The fields of an item that differ between two versions: `slots.<name>` and
// `rules.<id>` per slot and rule, else the item's own field name.
function changedFields(a, b) {
  const fields = [];
  const same = (x, y) => JSON.stringify(x) === JSON.stringify(y);
  for (const key of new Set([...Object.keys(a), ...Object.keys(b)])) {
    if (key === "edit" || key === "letter") continue;
    if (key === "slots") {
      for (const name of new Set([...Object.keys(a.slots ?? {}), ...Object.keys(b.slots ?? {})])) {
        if (!same(a.slots?.[name], b.slots?.[name])) fields.push(`slots.${name}`);
      }
    } else if (key === "rules") {
      const byId = (rules) => Object.fromEntries((rules ?? []).map((r) => [r.id, r]));
      const ra = byId(a.rules);
      const rb = byId(b.rules);
      for (const id of new Set([...Object.keys(ra), ...Object.keys(rb)])) {
        if (!same(ra[id], rb[id])) fields.push(`rules.${id}`);
      }
    } else if (!same(a[key], b[key])) {
      fields.push(key);
    }
  }
  return fields;
}

export function diff(fromParam, toParam) {
  const from = Number(fromParam);
  const to = Number(toParam);
  if (!Number.isInteger(from) || !Number.isInteger(to)) {
    return invalid([{ loc: ["query", "from"], msg: "from and to are version integers", type: "int_parsing" }]);
  }
  const a = findVersion(from);
  const b = findVersion(to);
  if (!a || !b) return fail(404, "not_found", `rule set version ${a ? to : from} does not exist`);
  const la = new Map(a.items.map((i) => [i.letter, i]));
  const lb = new Map(b.items.map((i) => [i.letter, i]));
  const changed = [];
  for (const [letter, item] of lb) {
    if (!la.has(letter)) continue;
    const fields = changedFields(la.get(letter), item);
    if (fields.length) changed.push({ letter, fields, edit: item.edit ?? null });
  }
  return ok({
    from,
    to,
    added: [...lb.keys()].filter((l) => !la.has(l)),
    removed: [...la.keys()].filter((l) => !lb.has(l)),
    changed,
  });
}

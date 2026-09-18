// The models of app/rulesets/schema.py, in JS, for the mock's rule-set routes.
// openapi.json types GET /ruleset, PUT /ruleset/draft and POST /ruleset/confirm
// as a bare dict and has no S3 item routes yet, so the mock validates what it
// accepts and what it answers against these instead. Keep them in step with
// schema.py; test/data and `python -c` in web/README.md check the fixtures
// against pydantic itself.
//
// Each validator returns pydantic-style errors, [{loc, msg, type}], which is
// what the API sends in `details.errors` of a 422 validation_failed. With
// `strict`, a field the model does not declare is an error too: pydantic would
// drop it, so a mock that answers with it lies about the contract.

export const DATA_CLASSES = ["synthetic", "redacted_sample", "confidential"];
export const CHECK_TYPES = [
  "filled", "value", "range", "unit", "date", "math", "tick_box", "signature",
  "document_present", "cross_document_match", "contains", "human_only",
];
export const PARTS = ["A", "B", "C"];
export const CONSEQUENCES = [
  "critical", "mandatory_on_request", "on_request_only", "deemed_compliance",
  "deemed_default", "discretionary", "no_gate",
];
export const ITEM_STATUSES = ["verified", "needs_input", "novel", "gap", "edited"];
export const OUTCOME_STATUSES = ["pass", "needs_review", "disqualified", "dormant"];
export const NOTE_KINDS = ["definition", "trigger", "consequence", "reference"];

// OUTCOME_KEYS: presence | positive | negative | neutral.
export const OUTCOME_KEYS = new Set([
  "blank", "filled", "redacted", "not_applicable",
  "match", "within_range", "within_precision", "valid", "compliant", "confirmed_compliant",
  "accredited", "on_time", "requested_and_met", "content_ok", "complete", "sealed",
  "bundled", "not_a_postal_box", "no_extra_charges", "receipt_confirmed",
  "effective_and_not_aborted",
  "mismatch", "outside_range", "exceeds_precision", "invalid", "non_compliant", "noncompliant",
  "expressly_non_compliant", "not_accredited", "late", "requested_and_missed", "content_wrong",
  "incomplete", "not_sealed", "not_bundled", "postal_box", "extra_charges_proposed",
  "no_receipt_evidence", "not_effective_or_aborted",
  "not_requested", "unstated", "na",
]);

const RULE_ID = /^[a-z][a-z0-9_.]*$/;
const LETTER = /^([a-z]|x[1-9][0-9]*)$/;
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$/;

class Ctx {
  constructor(strict) {
    this.strict = strict;
    this.errors = [];
  }
  add(loc, msg, type = "value_error") {
    this.errors.push({ loc, msg, type });
  }
}

const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
const isStr = (v) => typeof v === "string";

// Declared fields: [name, required, check(ctx, value, loc)]. A check may be
// null (any value).
function model(ctx, v, loc, fields) {
  if (!isObj(v)) {
    ctx.add(loc, "Input should be a valid dictionary or object", "model_type");
    return false;
  }
  const names = new Set(fields.map(([n]) => n));
  for (const [name, required, check] of fields) {
    if (!(name in v)) {
      if (required) ctx.add([...loc, name], "Field required", "missing");
      continue;
    }
    check?.(ctx, v[name], [...loc, name]);
  }
  if (ctx.strict) {
    for (const key of Object.keys(v)) if (!names.has(key)) ctx.add([...loc, key], "Extra inputs are not permitted", "extra_forbidden");
  }
  return true;
}

const nullable = (check) => (ctx, v, loc) => v === null || check(ctx, v, loc);
const str = (min = 0) => (ctx, v, loc) =>
  !isStr(v) ? ctx.add(loc, "Input should be a valid string", "string_type")
    : v.length < min ? ctx.add(loc, `String should have at least ${min} character`, "string_too_short") : null;
const pattern = (re) => (ctx, v, loc) =>
  !isStr(v) ? ctx.add(loc, "Input should be a valid string", "string_type")
    : !re.test(v) ? ctx.add(loc, `String should match pattern '${re.source}'`, "string_pattern_mismatch") : null;
const int = (min) => (ctx, v, loc) =>
  !Number.isInteger(v) ? ctx.add(loc, "Input should be a valid integer", "int_type")
    : min != null && v < min ? ctx.add(loc, `Input should be greater than or equal to ${min}`, "greater_than_equal") : null;
const bool = (ctx, v, loc) => (typeof v !== "boolean" ? ctx.add(loc, "Input should be a valid boolean", "bool_type") : null);
const oneOf = (values) => (ctx, v, loc) =>
  !values.includes(v) ? ctx.add(loc, `Input should be ${values.map((x) => `'${x}'`).join(", ")}`, "enum") : null;
const datetime = (ctx, v, loc) => (!isStr(v) || !ISO.test(v) ? ctx.add(loc, "Input should be a valid datetime", "datetime_type") : null);
const list = (check) => (ctx, v, loc) =>
  !Array.isArray(v) ? ctx.add(loc, "Input should be a valid list", "list_type") : v.forEach((x, i) => check(ctx, x, [...loc, i]));
const dict = (check) => (ctx, v, loc) =>
  !isObj(v) ? ctx.add(loc, "Input should be a valid dictionary", "dict_type") : Object.entries(v).forEach(([k, x]) => check(ctx, x, [...loc, k]));

function citation(ctx, v, loc) {
  model(ctx, v, loc, [
    ["file", true, str()],
    ["page", true, int(1)],
    ["node_id", false, nullable(str())],
    ["quote", true, str(1)],
    ["data_class", true, oneOf(DATA_CLASSES)],
  ]);
}

function edit(ctx, v, loc) {
  model(ctx, v, loc, [
    ["by", true, str()],
    ["at", true, datetime],
    ["reason", true, str(1)],
  ]);
}

function slotValue(ctx, v, loc) {
  if (!model(ctx, v, loc, [
    ["value", false, null],
    ["citation", false, nullable(citation)],
    ["verified", false, bool],
    ["origin", false, oneOf(["extracted", "manual"])],
    ["model_value", false, null],
    ["edit", false, nullable(edit)],
  ])) return;
  const origin = v.origin ?? "extracted";
  const value = v.value ?? null;
  const cite = v.citation ?? null;
  if (value !== null && origin === "extracted" && cite === null) ctx.add(loc, "Value error, an extracted slot value must carry a citation");
  if (v.verified && cite === null) ctx.add(loc, "Value error, a value without a citation cannot be verified");
  if (origin === "manual" && (v.edit ?? null) === null) ctx.add(loc, "Value error, a manual value must record who set it and why");
}

function followUp(ctx, v, loc) {
  model(ctx, v, loc, [
    ["trigger", true, str(1)],
    ["deadline", true, str(1)],
    ["if_deadline_missed", true, oneOf(OUTCOME_STATUSES)],
  ]);
}

function outcome(ctx, v, loc) {
  if (!model(ctx, v, loc, [
    ["status", true, oneOf(OUTCOME_STATUSES)],
    ["note", false, nullable(str())],
    ["follow_up", false, nullable(followUp)],
  ])) return;
  if (v.follow_up != null && v.status !== "dormant") ctx.add(loc, "Value error, a follow_up belongs to a dormant outcome only");
}

function normalise(ctx, v, loc) {
  model(ctx, v, loc, [
    ["op", true, oneOf(["round_significant_figures", "resolve_range_to_lower_bound"])],
    ["params", false, dict(() => null)],
  ]);
}

function paramValue(ctx, v, loc) {
  const ok = ["string", "number", "boolean"].includes(typeof v) || (Array.isArray(v) && v.every(isStr));
  if (!ok) ctx.add(loc, "Input should be a string, number, boolean or list of strings", "union_tag_invalid");
}

export function templateRule(ctx, v, loc) {
  if (!model(ctx, v, loc, [
    ["id", true, pattern(RULE_ID)],
    ["check", true, oneOf(CHECK_TYPES)],
    ["field", true, str(1)],
    ["params", false, dict(paramValue)],
    ["consequence", false, nullable(oneOf(CONSEQUENCES))],
    ["outcomes", false, nullable(dict(outcome))],
    ["normalise", false, list(normalise)],
    ["stage", false, oneOf(["I", "II"])],
    ["condition", false, nullable(str())],
    ["depends_on", false, list(str())],
    ["note", false, nullable(str())],
  ])) return;
  if (v.consequence == null && v.outcomes == null) {
    ctx.add(loc, `Value error, rule ${v.id} needs a consequence or its own outcomes; a note belongs in ItemNote`);
  }
  if (isObj(v.outcomes)) {
    const unknown = Object.keys(v.outcomes).filter((k) => !OUTCOME_KEYS.has(k)).sort();
    if (unknown.length) ctx.add(loc, `Value error, rule ${v.id}: unknown outcome keys ${JSON.stringify(unknown)}; the vocabulary is closed (OUTCOME_KEYS)`);
  }
}

function itemNote(ctx, v, loc) {
  model(ctx, v, loc, [
    ["kind", true, oneOf(NOTE_KINDS)],
    ["text", true, str(1)],
    ["citation", false, nullable(citation)],
  ]);
}

function gap(ctx, v, loc) {
  model(ctx, v, loc, [
    ["node_id", true, str()],
    ["text", true, str()],
    ["reason", false, nullable(str())],
  ]);
}

function ruleSetItem(ctx, v, loc) {
  if (!model(ctx, v, loc, [
    ["letter", true, pattern(LETTER)],
    ["title", true, str(1)],
    ["part", true, oneOf(PARTS)],
    ["template", false, nullable(str())],
    ["citation", true, citation],
    ["clauses", false, list(citation)],
    ["condition", false, nullable(str())],
    ["notes", false, list(itemNote)],
    ["slots", false, dict(slotValue)],
    ["rules", false, list(templateRule)],
    ["status", true, oneOf(ITEM_STATUSES)],
    ["edit", false, nullable(edit)],
  ])) return;
  const rules = Array.isArray(v.rules) ? v.rules.filter(isObj) : [];
  const ids = rules.map((r) => r.id);
  if (new Set(ids).size !== ids.length) ctx.add(loc, `Value error, duplicate rule ids in item (${v.letter})`);
  if (v.template == null) {
    const without = rules.filter((r) => r.outcomes == null).map((r) => r.id);
    if (without.length) {
      ctx.add(loc, `Value error, item (${v.letter}) has no template, so its rules need their own outcomes: ${JSON.stringify(without)}`);
    }
  }
}

function ruleSet(ctx, v, loc) {
  if (!model(ctx, v, loc, [
    ["project_id", true, str(1)],
    ["version", true, int(1)],
    ["parent_version", false, nullable(int())],
    ["status", false, oneOf(["draft", "confirmed"])],
    ["data_class", true, oneOf(DATA_CLASSES)],
    ["items", true, list(ruleSetItem)],
    ["gaps", false, list(gap)],
    ["created_by", true, str()],
    ["created_at", true, datetime],
    ["confirmed_by", false, nullable(str())],
    ["confirmed_at", false, nullable(datetime)],
    ["model", false, nullable(str())],
    ["prompt_version", false, nullable(str())],
  ])) return;
  const items = Array.isArray(v.items) ? v.items.filter(isObj) : [];
  const letters = items.map((i) => i.letter);
  if (new Set(letters).size !== letters.length) ctx.add(loc, "Value error, item letters must be unique");
  if (v.parent_version != null && v.parent_version >= v.version) ctx.add(loc, "Value error, parent_version must be older than version");
  if (v.status === "confirmed") {
    if (!v.confirmed_by || !v.confirmed_at) ctx.add(loc, "Value error, a confirmed rule set records who confirmed it and when");
    const blocking = items.filter((i) => i.status === "needs_input" || i.status === "gap").map((i) => i.letter);
    if (blocking.length) ctx.add(loc, `Value error, items still need input or are gaps: ${JSON.stringify(blocking)}`);
    const unexplained = (Array.isArray(v.gaps) ? v.gaps : []).filter((g) => !g?.reason).map((g) => g?.node_id);
    if (unexplained.length) ctx.add(loc, `Value error, gaps without a reason: ${JSON.stringify(unexplained)}`);
  }
}

function run(check, value, strict) {
  const ctx = new Ctx(strict);
  check(ctx, value, []);
  return ctx.errors;
}

export const validateRuleSet = (v, { strict = false } = {}) => run(ruleSet, v, strict);
export const validateItem = (v, { strict = false } = {}) => run(ruleSetItem, v, strict);
export const validateRule = (v, { strict = false } = {}) => run(templateRule, v, strict);
export const validateCitation = (v, { strict = false } = {}) => run(citation, v, strict);
export const validateGap = (v, { strict = false } = {}) => run(gap, v, strict);
export const validateEdit = (v, { strict = false } = {}) => run(edit, v, strict);

// The S3 request and response shapes of docs/api_contract.md that openapi.json
// does not carry yet.
//   ItemPatch {slot?: {name, value}, rule?: TemplateRule, template?: str, note?: str, reason: str}
//   NewItem   {title, part, citation: Citation, rules: [TemplateRule], reason: str}
//   Diff      {from, to, added: [letter], removed: [letter], changed: [{letter, fields: [str], edit: Edit}]}
export function validateItemPatch(v) {
  const ctx = new Ctx(true);
  model(ctx, v, [], [
    ["slot", false, (c, s, loc) => model(c, s, loc, [["name", true, str(1)], ["value", true, null]])],
    ["rule", false, templateRule],
    ["template", false, nullable(str())],
    ["note", false, str(1)],
    ["reason", true, str(1)],
  ]);
  if (isObj(v) && !["slot", "rule", "template", "note"].some((k) => k in v)) {
    ctx.add([], "Value error, name a slot, a rule, the template or a note to change");
  }
  if (isObj(v) && isStr(v.reason) && !v.reason.trim() && !ctx.errors.some((e) => e.loc[0] === "reason")) {
    ctx.add(["reason"], "String should have at least 1 character", "string_too_short");
  }
  return ctx.errors;
}

export function validateNewItem(v) {
  const ctx = new Ctx(true);
  model(ctx, v, [], [
    ["title", true, str(1)],
    ["part", true, oneOf(PARTS)],
    ["citation", true, citation],
    ["rules", true, list(templateRule)],
    ["reason", true, str(1)],
  ]);
  if (isObj(v) && isStr(v.reason) && !v.reason.trim() && !ctx.errors.some((e) => e.loc[0] === "reason")) {
    ctx.add(["reason"], "String should have at least 1 character", "string_too_short");
  }
  return ctx.errors;
}

export function validateDiff(v) {
  const ctx = new Ctx(true);
  model(ctx, v, [], [
    ["from", true, int(1)],
    ["to", true, int(1)],
    ["added", true, list(pattern(LETTER))],
    ["removed", true, list(pattern(LETTER))],
    ["changed", true, list((c, x, loc) => model(c, x, loc, [
      ["letter", true, pattern(LETTER)],
      ["fields", true, list(str(1))],
      // The contract says `edit: Edit`; a change the model made (a rebuild)
      // has no human edit record, so the mock sends null there.
      ["edit", true, nullable(edit)],
    ]))],
  ]);
  return ctx.errors;
}

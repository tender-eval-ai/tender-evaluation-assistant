// The mock answers exactly like the contract: every mocked route exists in
// openapi.json, and every body it sends validates against the route's response
// schema, with no field the schema does not name. Reads ../docs/openapi.json.
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import * as fx from "./fixtures.js";
import { ROUTES } from "./handlers.js";
import {
  validateDiff,
  validateGap,
  validateItem,
  validateRuleSet,
} from "./rulesetSchema.js";

const here = dirname(fileURLToPath(import.meta.url));
const spec = JSON.parse(readFileSync(resolve(here, "../../docs/openapi.json"), "utf8"));
const BASE = "http://api.test";

function deref(schema) {
  if (schema?.$ref) return spec.components.schemas[schema.$ref.split("/").pop()];
  return schema;
}

function typeOk(type, v) {
  switch (type) {
    case "object":
      return v !== null && typeof v === "object" && !Array.isArray(v);
    case "array":
      return Array.isArray(v);
    case "string":
      return typeof v === "string";
    case "integer":
      return Number.isInteger(v);
    case "number":
      return typeof v === "number";
    case "boolean":
      return typeof v === "boolean";
    case "null":
      return v === null;
    default:
      return true;
  }
}

// A small JSON Schema subset, enough for FastAPI's output: $ref, type, enum,
// required, properties, additionalProperties, items, minItems, maxItems, anyOf. Strict on unknown
// properties: pydantic would drop them, so a mock that sends them lies.
export function validate(schemaIn, value, path = "$") {
  const schema = deref(schemaIn);
  if (!schema || Object.keys(schema).length === 0) return [];
  if (schema.anyOf) {
    const results = schema.anyOf.map((s) => validate(s, value, path));
    return results.some((r) => r.length === 0) ? [] : [`${path}: matches none of anyOf (${results.map((r) => r[0]).join(" | ")})`];
  }
  if (schema.enum && !schema.enum.includes(value)) return [`${path}: ${JSON.stringify(value)} not in ${schema.enum}`];
  if (schema.type && !typeOk(schema.type, value)) return [`${path}: expected ${schema.type}, got ${JSON.stringify(value)}`];
  const errors = [];
  if (schema.type === "array" && schema.minItems != null && value.length < schema.minItems) {
    errors.push(`${path}: ${value.length} items, fewer than ${schema.minItems}`);
  }
  if (schema.type === "array" && schema.maxItems != null && value.length > schema.maxItems) {
    errors.push(`${path}: ${value.length} items, more than ${schema.maxItems}`);
  }
  if (schema.type === "array" && schema.items) {
    value.forEach((v, i) => errors.push(...validate(schema.items, v, `${path}[${i}]`)));
  }
  if (schema.type === "object" || schema.properties) {
    const props = schema.properties ?? {};
    for (const key of schema.required ?? []) {
      if (!(key in value)) errors.push(`${path}: missing required '${key}'`);
    }
    for (const [key, v] of Object.entries(value)) {
      if (key in props) errors.push(...validate(props[key], v, `${path}.${key}`));
      else if (schema.additionalProperties === true) continue;
      else if (schema.additionalProperties) errors.push(...validate(schema.additionalProperties, v, `${path}.${key}`));
      else errors.push(`${path}: '${key}' is not in the contract`);
    }
  }
  return errors;
}

function responseSchema(method, path, status) {
  const op = spec.paths[path]?.[method];
  return op?.responses?.[String(status)]?.content?.["application/json"]?.schema;
}

const t = "Tenderer_A";
const doc = fx.TENDERERS[t].docId;
const REQUESTS = [
  ["get", "/projects", "/projects"],
  ["get", "/projects/{pid}", `/projects/${fx.PID}`],
  ["get", "/projects/{pid}/ruleset/versions", `/projects/${fx.PID}/ruleset/versions`],
  ["get", "/projects/{pid}/documents", `/projects/${fx.PID}/documents`],
  ["get", "/projects/{pid}/documents/{doc_id}/pages", `/projects/${fx.PID}/documents/${doc}/pages`],
  ...Object.keys(fx.TENDERERS)
    .filter((x) => x !== "Tenderer_B")
    .map((x) => ["get", "/projects/{pid}/bids/{tenderer}/results", `/projects/${fx.PID}/bids/${x}/results`]),
  ["get", "/projects/{pid}/jobs", `/projects/${fx.PID}/jobs`],
  ["get", "/projects/{pid}/events", `/projects/${fx.PID}/events`],
  ["get", "/projects/{pid}/price-summary", `/projects/${fx.PID}/price-summary`],
  ["get", "/projects/{pid}/evaluation", `/projects/${fx.PID}/evaluation`],
  ["get", "/projects/{pid}/reports", `/projects/${fx.PID}/reports`],
  ["get", "/settings", "/settings"],
  ["get", "/me", "/me"],
  ["get", "/inbox", "/inbox"],
];

describe("mock vs docs/openapi.json", () => {
  it("the checker itself rejects an unknown field, a missing field and a wrong enum", () => {
    const cite = { $ref: "#/components/schemas/PageCitation" };
    const ok = { doc_id: "9f849435aa64", file: "offer.pdf", page: 10, image_url: "/x" };
    expect(validate(cite, ok)).toEqual([]);
    expect(validate(cite, { ...ok, bbox: [0, 0, 1, 1] })).toEqual(["$: 'bbox' is not in the contract"]);
    expect(validate(cite, { ...ok, quote: "x", box: [0, 0, 1, 1], page_size: [595, 842] })).toEqual([]);
    expect(validate(cite, { ...ok, box: [0, 0, 1] })).toHaveLength(1);
    expect(validate(cite, { doc_id: "x", file: "f", page: 1 })).toEqual(["$: missing required 'image_url'"]);
    expect(validate({ $ref: "#/components/schemas/StageSummary" }, { outcome: "fail", items: {} })).toHaveLength(1);
  });

  it("serves only routes the contract has", () => {
    for (const [method, path] of ROUTES) {
      expect(spec.paths[path]?.[method], `${method.toUpperCase()} ${path}`).toBeDefined();
    }
  });

  it.each(REQUESTS)("%s %s answers with the contract's shape", async (method, path, url) => {
    const res = await fetch(BASE + url, { method: method.toUpperCase() });
    expect(res.status).toBe(200);
    const schema = responseSchema(method, path, 200);
    expect(schema, `no 200 schema for ${path}`).toBeDefined();
    expect(validate(schema, await res.json())).toEqual([]);
  });

  it("the front door: a new project, its case imported, its first draft a Job", async () => {
    const post = (url, b) => fetch(BASE + url, { method: "POST", headers: { "Content-Type": "application/json" },
                                                 body: JSON.stringify(b) });
    const created = await post("/projects", { name: "Small tender, try 1", data_class: "synthetic" });
    const project = await created.json();
    expect(validate(responseSchema("post", "/projects", 200), project)).toEqual([]);
    expect((await post(`/projects/${project.id}/import`, { path: "synthetic_tender" })).status).toBe(200);
    const started = await post(`/projects/${project.id}/ruleset/build`, {});
    expect(started.status).toBe(202);
    const { job_id } = await started.json();
    const job = await (await fetch(`${BASE}/projects/${project.id}/jobs/${job_id}`)).json();
    expect(validate(responseSchema("get", "/projects/{pid}/jobs/{job_id}", 200), job)).toEqual([]);
    expect(job.kind).toBe("ruleset_build");
    const listed = await (await fetch(`${BASE}/projects`)).json();
    expect(listed.map((p) => p.id)).toContain(project.id);
  });

  it("the synthetic case's card is the one the case folder carries", () => {
    const card = JSON.parse(readFileSync(resolve(here, "../../test/data/synthetic_tender/case.json"), "utf8"));
    expect(fx.CASE_CARD).toEqual(card);
  });

  it("POST /checks answers 202 CheckResponse, and the job it starts is a Job", async () => {
    const res = await fetch(`${BASE}/projects/${fx.PID}/checks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenderers: ["Tenderer_B"] }),
    });
    expect(res.status).toBe(202);
    const body = await res.json();
    expect(validate(responseSchema("post", "/projects/{pid}/checks", 202), body)).toEqual([]);
    const job = await (await fetch(`${BASE}/projects/${fx.PID}/jobs/${body.job_ids.Tenderer_B}`)).json();
    expect(validate(responseSchema("get", "/projects/{pid}/jobs/{job_id}", 200), job)).toEqual([]);
    expect(job.progress).toEqual({ done: 1, total: 3, unit: "items" });
  });

  it("citations carry a signed, relative image link and never an API key", async () => {
    const result = fx.bidResult(t);
    const urls = Object.values(result.verdicts).flatMap((v) => v.evidence.map((e) => e.image_url));
    expect(urls.length).toBeGreaterThan(0);
    for (const u of urls) {
      expect(u).toMatch(/^\/projects\/[^/]+\/documents\/[0-9a-f]{12}\/pages\/\d+\/image\?exp=\d+&sig=\w+(&highlight=[^&]+)?$/);
      expect(u).not.toMatch(/key/i);
    }
  });

  it("a citation on a text layer carries its quote, box and a signed highlight; a scanned one none", () => {
    const quoted = fx.bidResult(t).fields.l.tenderer_name.page;
    expect(quoted.quote).toBe(fx.TENDERERS[t].name);
    expect(quoted.box).toHaveLength(4);
    expect(quoted.page_size).toEqual([595, 842]);
    expect(new URL(quoted.image_url, BASE).searchParams.get("highlight")).toBe(quoted.quote);
    // A boolean is not text on the page: the plain page.
    const plain = fx.bidResult(t).fields.l.document.page;
    expect([plain.quote, plain.box, plain.page_size]).toEqual([null, null, null]);
    expect(plain.image_url).not.toMatch(/highlight/);
    // Tenderer_D's offer is scanned: its name is read, but there is no text layer.
    const scanned = fx.bidResult("Tenderer_D").fields.l.tenderer_name.page;
    expect([scanned.quote, scanned.box, scanned.page_size]).toEqual([null, null, null]);
    expect(scanned.image_url).not.toMatch(/highlight/);
  });

  it("documents carry the project path a rule set Citation.file names", () => {
    const docs = fx.documents();
    expect(docs.find((d) => d.doc_id === doc).path).toBe(`bids/${t}/offer.pdf`);
    expect(docs.find((d) => d.file === "09 Schedules.pdf").path).toBe("tender/09 Schedules.pdf");
  });

  it("a tampered signed highlight is refused with 403 in the error envelope", async () => {
    const signed = fx.bidResult(t).fields.l.tenderer_name.page.image_url;
    expect((await fetch(BASE + signed)).status).toBe(200);
    const url = new URL(signed, BASE);
    url.searchParams.set("highlight", "Tenderer B Chemicals Ltd");
    const res = await fetch(url);
    expect(res.status).toBe(403);
    expect((await res.json()).error).toEqual({ code: "forbidden", message: expect.any(String), details: {} });
    url.searchParams.delete("highlight");
    expect((await fetch(url)).status).toBe(403);
  });

  it("errors use the {error: {code, message, details}} envelope", async () => {
    for (const url of [`/projects/nope`, `/projects/${fx.PID}/bids/Tenderer_B/results`, `/projects/${fx.PID}/jobs/job-9999`]) {
      const res = await fetch(BASE + url);
      expect(res.status).toBe(404);
      const body = await res.json();
      expect(body.error).toEqual({ code: "not_found", message: expect.any(String), details: {} });
    }
  });

  it("draws the highlight on the page image only when asked", async () => {
    const page = fx.TENDERERS[t].l;
    const signed = fx.imageUrl(doc, page);
    const plain = await (await fetch(BASE + signed)).text();
    expect(plain).not.toContain("data-highlight");
    const marked = await (await fetch(`${BASE}${signed}&highlight=${encodeURIComponent(fx.TENDERERS[t].name)}`)).text();
    expect(marked).toContain('data-highlight="true"');
    expect((await fetch(`${BASE}/projects/${fx.PID}/documents/${doc}/pages/${page}/image`)).status).toBe(403);
    expect((await fetch(`${BASE}${signed.replace(/sig=\w+/, "sig=mock00000000")}`)).status).toBe(403);
  });

  it("both rule set fixtures carry the RuleSet fields of app/rulesets/schema.py", () => {
    expect(validateRuleSet(fx.ruleset, { strict: true })).toEqual([]);
    expect(validateRuleSet(fx.rulesetDraft, { strict: true })).toEqual([]);
    expect(Object.keys(fx.rulesetDraft).sort()).toEqual(Object.keys(fx.ruleset).sort());
    // GET /ruleset is untyped in openapi.json (a dict), so the RuleSet shape
    // is checked by hand here; `python -c` in web/README.md validates it
    // against the pydantic model itself.
    expect(Object.keys(fx.ruleset).sort()).toEqual(
      [
        "project_id", "version", "parent_version", "status", "data_class", "items", "gaps",
        "created_by", "created_at", "confirmed_by", "confirmed_at", "model", "prompt_version",
      ].sort()
    );
    const l = fx.ruleset.items.find((i) => i.letter === "l");
    expect(l.title).toMatch(/Non-collusive Tendering Certificate/);
    expect(l.part).toBe("A");
  });
});

// The S3 rule-set routes. openapi.json types GET /ruleset, PUT /draft and POST
// /confirm as a bare dict and has no diff, gaps or item routes yet, so their
// bodies are checked against the models of app/rulesets/schema.py
// (mock/rulesetSchema.js, strict on unknown fields). A route that appears in
// openapi.json later is checked against it as well.
describe("mock rule-set routes (S3) vs app/rulesets/schema.py", () => {
  const R = `${BASE}/projects/${fx.PID}/ruleset`;
  const call = (method, url, body, user = "nasi") =>
    fetch(url, {
      method,
      headers: { "Content-Type": "application/json", "X-User": user },
      body: body === undefined ? undefined : JSON.stringify(body),
    });

  function inContract(method, path, status, body) {
    const schema = responseSchema(method, path, status);
    return schema ? validate(schema, body) : [];
  }

  it("GET /ruleset is the latest draft; ?version= a confirmed one; both RuleSets", async () => {
    const draft = await (await fetch(R)).json();
    expect(draft).toMatchObject({ version: 2, parent_version: 1, status: "draft" });
    expect(validateRuleSet(draft, { strict: true })).toEqual([]);
    const v1 = await (await fetch(`${R}?version=1`)).json();
    expect(v1.status).toBe("confirmed");
    expect(validateRuleSet(v1, { strict: true })).toEqual([]);
    expect((await fetch(`${R}?version=9`)).status).toBe(404);
  });

  it("GET /gaps is [Gap]", async () => {
    const gaps = await (await fetch(`${R}/gaps`)).json();
    expect(gaps).toHaveLength(2);
    for (const g of gaps) expect(validateGap(g, { strict: true })).toEqual([]);
  });

  it("GET /diff is a Diff", async () => {
    const res = await fetch(`${R}/diff?from=1&to=2`);
    const d = await res.json();
    expect(validateDiff(d)).toEqual([]);
    expect(d).toMatchObject({ from: 1, to: 2, added: ["c"], removed: [] });
    expect(d.changed).toEqual([
      {
        letter: "k",
        fields: ["rules.contact_details.contact_person", "status"],
        edit: expect.objectContaining({ by: "chenyu" }),
      },
    ]);
    expect((await fetch(`${R}/diff?from=1&to=7`)).status).toBe(404);
  });

  it("PATCH an item: reason required; a slot keeps model_value; status edited, attributed", async () => {
    const noReason = await call("PATCH", `${R}/items/c`, { slot: { name: "estimated_quantity", value: 1250 } });
    expect(noReason.status).toBe(422);
    expect((await noReason.json()).error).toMatchObject({ code: "validation_failed", details: { errors: [expect.objectContaining({ loc: ["reason"] })] } });
    const blank = await call("PATCH", `${R}/items/c`, { slot: { name: "estimated_quantity", value: 1250 }, reason: "  " });
    expect(blank.status).toBe(422);

    const res = await call("PATCH", `${R}/items/c`, {
      slot: { name: "estimated_quantity", value: 1250 },
      reason: "Addendum 1 raised the estimate",
    });
    expect(res.status).toBe(200);
    const item = await res.json();
    expect(validateItem(item, { strict: true })).toEqual([]);
    expect(item.status).toBe("edited");
    expect(item.edit).toMatchObject({ by: "nasi", reason: "Addendum 1 raised the estimate" });
    expect(item.slots.estimated_quantity).toMatchObject({ value: 1250, model_value: 1200, origin: "manual", verified: false });
    // A second correction keeps the model's value, not the first person's.
    const again = await (await call("PATCH", `${R}/items/c`, { slot: { name: "estimated_quantity", value: 1300 }, reason: "typo" })).json();
    expect(again.slots.estimated_quantity).toMatchObject({ value: 1300, model_value: 1200 });
  });

  it("PATCH a rule that is no gate answers 422 with pydantic-style errors", async () => {
    const res = await call("PATCH", `${R}/items/a`, {
      rule: { id: "offer_to_be_bound.dated", check: "date", field: "offer_to_be_bound.date" },
      reason: "the form is dated",
    });
    expect(res.status).toBe(422);
    const { error } = await res.json();
    expect(error.code).toBe("validation_failed");
    expect(error.details.errors[0].msg).toMatch(/needs a consequence or its own outcomes/);
  });

  it("POST an item from a selected clause: letter x1, the selection is its citation", async () => {
    const citation = { file: "tender/04 Terms of Tender (Supplement).pdf", page: 5, quote: "A sample shall be submitted", data_class: "synthetic" };
    const res = await call("POST", `${R}/items`, {
      title: "Product sample",
      part: "B",
      citation,
      rules: [{ id: "sample.submitted", check: "document_present", field: "sample.document", outcomes: { blank: { status: "needs_review" }, filled: { status: "pass" } } }],
      reason: "The supplement asks for a sample",
    });
    expect(res.status).toBe(200);
    const item = await res.json();
    expect(item).toMatchObject({ letter: "x1", status: "edited", citation: { ...citation, node_id: null } });
    // Defaults filled, as pydantic dumps them.
    expect(item.rules[0]).toMatchObject({ stage: "I", depends_on: [], normalise: [], consequence: null });
    expect(item.rules[0].outcomes.blank).toEqual({ status: "needs_review", note: null, follow_up: null });
    expect(validateItem(item, { strict: true })).toEqual([]);
  });

  it("DELETE an item needs a reason and answers 204", async () => {
    expect((await call("DELETE", `${R}/items/k`, {})).status).toBe(422);
    const res = await call("DELETE", `${R}/items/k`, { reason: "Covered by (a)" });
    expect(res.status).toBe(204);
    const d = await (await fetch(`${R}/diff?from=1&to=2`)).json();
    expect(d.removed).toEqual(["k"]);
    expect((await call("DELETE", `${R}/items/k`, { reason: "again" })).status).toBe(404);
  });

  it("PUT /draft validates the whole draft; 422 validation_failed lists the errors", async () => {
    const draft = await (await fetch(R)).json();
    const bad = { ...draft, items: [{ ...draft.items[0], part: "Z" }] };
    const res = await call("PUT", `${R}/draft`, bad);
    expect(res.status).toBe(422);
    const { error } = await res.json();
    expect(error.code).toBe("validation_failed");
    expect(error.details.errors).toEqual([expect.objectContaining({ loc: ["items", 0, "part"] })]);

    const good = await call("PUT", `${R}/draft`, { ...draft, gaps: draft.gaps.map((g) => ({ ...g, reason: g.reason ?? "Sample handled at plant trial" })) });
    expect(good.status).toBe(200);
    const saved = await good.json();
    expect(inContract("put", "/projects/{pid}/ruleset/draft", 200, saved)).toEqual([]);
    expect(validateRuleSet(saved, { strict: true })).toEqual([]);
    expect(saved).toMatchObject({ version: 2, status: "draft" });
  });

  it("POST /confirm: 409 while an item needs input or a gap has no reason, 403 for the last editor, then version N", async () => {
    const blocked = await call("POST", `${R}/confirm`, {}, "nasi");
    expect(blocked.status).toBe(409);
    const { error } = await blocked.json();
    expect(error.code).toBe("conflict");
    expect(error.details.errors.map((e) => e.msg).join(" ")).toMatch(/\["c"\].*Supp:13:\(d\)/);

    const draft = await (await fetch(R)).json();
    await call("PUT", `${R}/draft`, {
      ...draft,
      items: draft.items.map((i) => (i.letter === "c" ? { ...i, status: "verified" } : i)),
      gaps: draft.gaps.map((g) => ({ ...g, reason: g.reason ?? "Sample handled at plant trial" })),
    }, "nasi");

    const self = await call("POST", `${R}/confirm`, {}, "nasi");
    expect(self.status).toBe(403);
    expect((await self.json()).error.code).toBe("self_approval");

    const res = await call("POST", `${R}/confirm`, {}, "chenyu");
    expect(res.status).toBe(200);
    const confirmed = await res.json();
    expect(inContract("post", "/projects/{pid}/ruleset/confirm", 200, confirmed)).toEqual([]);
    expect(validateRuleSet(confirmed, { strict: true })).toEqual([]);
    expect(confirmed).toMatchObject({ version: 2, status: "confirmed", confirmed_by: "chenyu" });

    const versions = await (await fetch(`${R}/versions`)).json();
    expect(validate(responseSchema("get", "/projects/{pid}/ruleset/versions", 200), versions)).toEqual([]);
    expect(versions.map((v) => [v.version, v.status])).toEqual([[1, "confirmed"], [2, "confirmed"]]);
    expect((await call("POST", `${R}/confirm`, {}, "chenyu")).status).toBe(409);

    // Editing a confirmed set opens draft v3 whose parent is v2.
    await call("PATCH", `${R}/items/a`, { note: "Signed by an authorised signatory", reason: "clarify" }, "nasi");
    const v3 = await (await fetch(R)).json();
    expect(v3).toMatchObject({ version: 3, parent_version: 2, status: "draft", created_by: "nasi" });
  });

  it("every edit is an event with who and why", async () => {
    await call("DELETE", `${R}/items/k`, { reason: "Covered by (a)" }, "nasi");
    const { items } = await (await fetch(`${BASE}/projects/${fx.PID}/events`)).json();
    expect(validate(responseSchema("get", "/projects/{pid}/events", 200), { items, next_cursor: null })).toEqual([]);
    expect(items.at(-1)).toMatchObject({ kind: "ruleset.item_deleted", user: "nasi", reason: "Covered by (a)", subject: "v2:k" });
  });
});

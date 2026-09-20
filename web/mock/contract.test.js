// The mock answers exactly like the contract: every mocked route exists in
// openapi.json, and every body it sends validates against the route's response
// schema, with no field the schema does not name. Reads ../docs/openapi.json
// once PR #27 has put it on main, else the S2 snapshot beside this file.
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import * as fx from "./fixtures.js";
import { ROUTES } from "./handlers.js";

const here = dirname(fileURLToPath(import.meta.url));
const repoSpec = resolve(here, "../../docs/openapi.json");
const specPath = existsSync(repoSpec) ? repoSpec : resolve(here, "openapi.s2.json");
const spec = JSON.parse(readFileSync(specPath, "utf8"));
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
// required, properties, additionalProperties, items, anyOf. Strict on unknown
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
];

describe(`mock vs ${specPath.includes("docs/openapi.json") ? "docs/openapi.json" : "openapi.s2.json (PR #27)"}`, () => {
  it("the checker itself rejects an unknown field, a missing field and a wrong enum", () => {
    const cite = { $ref: "#/components/schemas/PageCitation" };
    const ok = { doc_id: "9f849435aa64", file: "offer.pdf", page: 10, image_url: "/x" };
    expect(validate(cite, ok)).toEqual([]);
    // A name the contract will never have, so this cannot go stale the way
    // `box` did once the citation box became a real PageCitation field.
    expect(validate(cite, { ...ok, not_a_contract_field: 1 }))
      .toEqual(["$: 'not_a_contract_field' is not in the contract"]);
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
      expect(u).toMatch(/^\/projects\/[^/]+\/documents\/[0-9a-f]{12}\/pages\/\d+\/image\?exp=\d+&sig=\w+$/);
      expect(u).not.toMatch(/key/i);
    }
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
  });

  it("the rule set fixture carries the RuleSet fields of app/rulesets/schema.py", () => {
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

// Small helpers shared by the Rules window's panels.

// A slot or param value as typed: JSON when it parses (1200, true, ["a"]),
// else the text itself; an empty box is null.
export function parseValue(text) {
  const t = text.trim();
  if (!t) return null;
  try {
    return JSON.parse(t);
  } catch {
    return t;
  }
}

export function showValue(v) {
  if (v === null || v === undefined) return "—";
  return typeof v === "string" ? v : JSON.stringify(v);
}

export function when(iso) {
  if (!iso) return "";
  const d = typeof iso === "number" ? new Date(iso * 1000) : new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString();
}

// What stops a draft from being confirmed (RuleSet._consistent in
// app/rulesets/schema.py): items that need input or are gaps, and gaps
// without a reason.
export function blockers(ruleset) {
  if (!ruleset || ruleset.status !== "draft") return { items: [], gaps: [] };
  return {
    items: ruleset.items.filter((i) => i.status === "needs_input" || i.status === "gap"),
    gaps: (ruleset.gaps ?? []).filter((g) => !g.reason),
  };
}

// A rule id from an item title: "Product sample" -> "product_sample".
export function slug(text) {
  const s = String(text ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^[^a-z]+|_+$/g, "");
  return s || "added_item";
}

// The rule an added item starts with: the document is present. A person adds
// an item without a template, so the rule carries its own outcomes, by Part.
const BLANK_BY_PART = {
  A: { status: "disqualified", note: "{field} is missing; the tender is not considered further (Part A)" },
  B: { status: "needs_review", note: "{field} is missing; the Tendering Authority may request it (Part B)" },
  C: { status: "pass", note: "{field} is missing; the Tendering Authority may request it later (Part C)" },
};

export function defaultRule(title, part) {
  const id = slug(title);
  return {
    id: `${id}.submitted`,
    check: "document_present",
    field: `${id}.document`,
    outcomes: {
      blank: { ...BLANK_BY_PART[part] },
      filled: { status: "pass" },
      redacted: { status: "needs_review", note: "{field} is covered by a black bar in this copy; a reviewer checks the original" },
    },
  };
}

// pydantic's error location, e.g. ["items", 0, "part"] -> items[0].part
export function locText(loc) {
  return (loc ?? []).reduce(
    (out, part) => (typeof part === "number" ? `${out}[${part}]` : out ? `${out}.${part}` : String(part)),
    ""
  );
}

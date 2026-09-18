// Every response the mock serves is built here, from synthetic data only: the
// SYN-2026-001 case in test/data/synthetic_tender (tools/make_synthetic_tender.py). No tender
// numbers, vendor names or values from a real tender.
//
// Shapes follow docs/api_contract.md and docs/openapi.json (PR #27,
// feat/checks-api). contract.test.js fetches every mocked route and checks the
// body against the OpenAPI schemas, so a drift fails `npx vitest run`.
import ruleset from "./fixtures/ruleset.json";
import rulesetDraft from "./fixtures/ruleset_draft.json";

export const PID = "syn-2026-001";
export const RULESET_VERSION = 1;
const T0 = 1789646400; // 2026-09-17T12:00:00Z, seconds (the API's float timestamps)

// Documents: doc_id is what backend/deps.py computes, sha1(<path relative to
// the project>)[:12], so a fixture page can be compared with the real route.
const TENDER_DOCS = [
  ["93ebccbc0463", "00 Guidelines for Electronic Tendering.pdf", 2],
  ["12522d32c002", "01 Tender Form.pdf", 4],
  ["22c05aafe668", "02 Interpretation, Terms of Tender and General Conditions of Contract.pdf", 16],
  ["8e7719079f7e", "03 Interpretation (Supplement).pdf", 2],
  ["233f60279a4f", "04 Terms of Tender (Supplement).pdf", 10],
  ["aafceea5af20", "05 Annex A (Reply Slip) to the Terms of Tender (Supplement).pdf", 1],
  ["d3047c8636d5", "06 Annex B (Procedures and Conditions of Plant Trial) to the Terms of Tender (Supplement).pdf", 1],
  ["f6f597985599", "07 Special Conditions of Contract.pdf", 4],
  ["30314ba9bf0c", "08 Technical Specifications.pdf", 2],
  ["94a33c47b5ba", "08A Attachment A to the Technical Specifications.pdf", 2],
  ["d4b2a16cf055", "08B Attachment B to the Technical Specifications.pdf", 2],
  ["6be51e1eecb6", "08C Attachment C to the Technical Specifications.pdf", 1],
  ["530747b5c5fc", "08D Attachment D to the Technical Specifications.pdf", 1],
  ["ca2b028fe7a7", "09 Schedules.pdf", 8],
  ["8659abe6ee62", "10 Non-collusive Tendering Certificate.pdf", 2],
  ["ab9f4cbdd51b", "11 Appendix to the Terms of Tender - Contact Details.pdf", 1],
  ["f0927d321d0d", "12 Annex A to the Terms of Tender Part I - Method of Production Statement.pdf", 1],
];

// Per tenderer: the offer's doc_id and page count, the pages items (a), (k)
// and (l) sit on (ground_truth.json), and the synthetic name printed on them.
export const TENDERERS = {
  Tenderer_A: { docId: "9f849435aa64", pages: 12, scanned: false, name: "Tenderer A Chemicals Ltd", a: 2, k: 9, l: 10 },
  Tenderer_B: { docId: "941e26ebfe0d", pages: 16, scanned: true, name: "Tenderer B Chemicals Ltd", a: 2, k: 12, l: 13 },
  Tenderer_C: { docId: "f2efd5f29611", pages: 12, scanned: false, name: "Tenderer C Chemicals Ltd", a: 2, k: 9, l: null },
  Tenderer_D: { docId: "4283c67edc8e", pages: 16, scanned: true, name: "Tenderer D Trading Ltd", a: 2, k: 12, l: 13 },
};

export const project = {
  id: PID,
  name: "Supply of Synthetic Coagulant Granules (Type S)",
  created: T0,
  synthetic: true,
  data_class: "synthetic",
  status: "idle",
};

export function projectDetail() {
  return {
    ...project,
    tender_files: TENDER_DOCS.map(([, file]) => file),
    bidders: Object.keys(TENDERERS),
    extracted: [],
    has_rubric: false,
    has_evaluation: false,
    reports: [],
  };
}

export { ruleset, rulesetDraft };

export function documents() {
  return [
    ...TENDER_DOCS.map(([doc_id, file, pages]) => ({
      doc_id,
      file,
      path: `tender/${file}`,
      kind: "tender",
      tenderer: null,
      pages,
      data_class: "synthetic",
    })),
    ...Object.entries(TENDERERS).map(([t, info]) => ({
      doc_id: info.docId,
      file: "offer.pdf",
      path: `bids/${t}/offer.pdf`,
      kind: "bid",
      tenderer: t,
      pages: info.pages,
      data_class: "synthetic",
    })),
  ];
}

export function findDocument(docId) {
  return documents().find((d) => d.doc_id === docId) ?? null;
}

// Signed, short-lived link as backend/signing.py builds it: relative to the
// API, `exp` and `sig` in the query, never the API key. A citation with a
// quote signs `highlight` too, so changing it breaks the signature. The mock's
// "HMAC" is FNV-1a: enough to tell a tampered link from a signed one.
export function sign(docId, page, exp, highlight = null) {
  let h = 0x811c9dc5;
  for (const c of `${PID}|${docId}|${page}|${exp}${highlight ? `|${highlight}` : ""}`) {
    h = Math.imul(h ^ c.codePointAt(0), 0x01000193) >>> 0;
  }
  return `mock${h.toString(16).padStart(8, "0")}`;
}

// As backend/signing.py verify(): a link signed with this highlight, or a
// page-only link (a client-added highlight on it still opens, until S3).
export function verify(docId, page, exp, sig, highlight = null) {
  if (!exp || !sig || Number(exp) < Math.floor(Date.now() / 1000)) return false;
  if (highlight && sig === sign(docId, page, exp, highlight)) return true;
  return sig === sign(docId, page, exp);
}

export function imageUrl(docId, page, highlight = null) {
  const exp = Math.floor(Date.now() / 1000) + 15 * 60;
  const query = new URLSearchParams({ exp: String(exp), sig: sign(docId, page, exp, highlight) });
  if (highlight) query.set("highlight", highlight);
  return `/projects/${PID}/documents/${docId}/pages/${page}/image?${query}`;
}

const BID_PAGE_LABELS = { a: "tender_form_offer_to_be_bound", k: "contact_details", l: "noncollusive_certificate" };

export function pages(docId) {
  const doc = findDocument(docId);
  if (!doc) return null;
  const bid = doc.kind === "bid" ? TENDERERS[doc.tenderer] : null;
  return Array.from({ length: doc.pages }, (_, i) => {
    const n = i + 1;
    const letter = bid ? Object.keys(BID_PAGE_LABELS).find((l) => bid[l] === n) : null;
    return {
      page: n,
      has_text: !bid?.scanned,
      label: letter ? BID_PAGE_LABELS[letter] : bid ? "other" : null,
      title: null,
      summary: null,
      signed: letter ? true : null,
      has_table: null,
      image_url: imageUrl(docId, n),
    };
  });
}

// What is printed on a page, for the mock's page images. Only the pages a
// citation points at have real lines; every other page is a placeholder.
export function pageLines(docId, page) {
  const doc = findDocument(docId);
  if (!doc) return [];
  if (doc.kind === "bid") {
    const t = TENDERERS[doc.tenderer];
    if (page === t.l) {
      return [
        "NON-COLLUSIVE TENDERING CERTIFICATE",
        "Tender Ref.: SYN-2026-001",
        "We certify that this tender is made without any agreement,",
        "arrangement or understanding with any other tenderer.",
        `Name of Tenderer: ${t.name}`,
        "Signature: [signed]",
        "Date: 1 September 2026",
      ];
    }
    if (page === t.a) {
      return ["TENDER FORM - OFFER TO BE BOUND", "Tender Ref.: SYN-2026-001", `For and on behalf of: ${t.name}`, "Signature: [signed]"];
    }
    if (page === t.k) {
      return [
        "APPENDIX - CONTACT DETAILS",
        `Name of Tenderer: ${t.name}`,
        t.scanned && doc.tenderer === "Tenderer_B" ? "Contact person: [illegible]" : "Contact person: Pat Example",
      ];
    }
    return [`${doc.tenderer} offer, page ${page}`, "(synthetic placeholder page)"];
  }
  // A tender page prints the rule set's quotes that cite it, so a quote the
  // Rules window asks to highlight is found on the page.
  const quotes = [...new Map([...ruleset.items, ...rulesetDraft.items].map((i) => [i.letter, i])).values()]
    .flatMap((item) => [
      item.citation,
      ...item.clauses,
      ...Object.values(item.slots).map((s) => s.citation).filter(Boolean),
    ])
    .filter((c) => c.file === `tender/${doc.file}` && c.page === page)
    .map((c) => c.quote)
    .filter((q, i, all) => all.indexOf(q) === i);
  return [doc.file.replace(/\.pdf$/, "").toUpperCase(), ...quotes.flatMap((q) => wrap(q, 60)), `page ${page}`];
}

function wrap(text, width) {
  const lines = [];
  let line = "";
  for (const word of text.split(" ")) {
    if (line && (line + " " + word).length > width) {
      lines.push(line);
      line = word;
    } else {
      line = line ? `${line} ${word}` : word;
    }
  }
  if (line) lines.push(line);
  return lines;
}

// The mock's page images (handlers.js pageSvg) are A4 in points, one line of
// text per row: row i has its baseline at y = 110 + 34 i, body text 15 pt at
// about 7.5 pt per character from x = 60. PAGE_SIZE and lineBox() are that
// layout, so a box drawn over the image lands on the printed text.
export const PAGE_SIZE = [595, 842];
export const lineY = (i) => 110 + i * 34;

export function lineBox(i, start, length) {
  const cw = i === 0 ? 10 : 7.5;
  const y = lineY(i);
  return [60 + start * cw, y - 16, 60 + (start + length) * cw, y + 5];
}

// Where `text` is printed on a page's text layer, as backend/routes/checks.py
// locate_quote() answers: {quote, box, page_size}, or null on a scanned offer,
// for text shorter than 4 characters, or when the page does not print it.
export function locateQuote(docId, page, text) {
  const doc = findDocument(docId);
  if (!doc || typeof text !== "string" || text.trim().length < 4) return null;
  if (doc.kind === "bid" && TENDERERS[doc.tenderer].scanned) return null;
  const needle = text.trim().toLowerCase();
  const lines = pageLines(docId, page);
  for (let i = 0; i < lines.length; i++) {
    const start = lines[i].toLowerCase().indexOf(needle);
    if (start >= 0) {
      return {
        quote: lines[i].slice(start, start + needle.length),
        box: lineBox(i, start, needle.length),
        page_size: [...PAGE_SIZE],
      };
    }
  }
  return null;
}

// A PageCitation. With `text` found on the page, it carries the quote, its box
// and an image link with the highlight signed in; otherwise the plain page.
function cite(t, page, text = null) {
  const info = TENDERERS[t];
  const at = locateQuote(info.docId, page, text);
  return {
    doc_id: info.docId,
    file: "offer.pdf",
    page,
    image_url: imageUrl(info.docId, page, at?.quote ?? null),
    quote: at?.quote ?? null,
    box: at?.box ?? null,
    page_size: at?.page_size ?? null,
  };
}

function fv(value, t, page, confidence = 0.96) {
  return { value, redacted: false, confidence, page: page ? cite(t, page, value) : null, correction: null, model_value: null };
}

function checked(field_id, status, note = null) {
  return { field_id, status, note, redacted: false, stage: "I", follow_up: null };
}

const RANK = { disqualified: 3, needs_review: 2, pass: 1, dormant: 0 };
function worstOf(statuses) {
  return statuses.reduce((w, s) => (RANK[s] > RANK[w] ? s : w), "pass");
}

function verdict(part, ruleIds, checks, evidence) {
  const active = checks.filter((c) => c.status !== "dormant").map((c) => c.status);
  const outcome = worstOf(active);
  return {
    outcome,
    worst: worstOf(checks.map((c) => c.status)),
    part,
    rule_ids: ruleIds,
    reason: checks.filter((c) => c.note).map((c) => c.note).join("; "),
    checks,
    evidence,
  };
}

// BidResult per tenderer. A: all pass, (l) on p.10. B (scanned): the contact
// person is illegible, so (k) needs review. C: no certificate, so (l)
// disqualifies. D: all pass.
export function bidResult(t) {
  const info = TENDERERS[t];
  if (!info) return null;
  const contactOk = t !== "Tenderer_B";
  const hasL = info.l != null;

  const fields = {
    a: {
      document: fv(true, t, info.a),
      signature: fv(true, t, info.a, 0.91),
    },
    k: {
      document: fv(true, t, info.k),
      contact_person: contactOk ? fv("Pat Example", t, info.k) : fv(null, t, info.k, 0.31),
    },
    l: hasL
      ? {
          document: fv(true, t, info.l),
          signature: fv(true, t, info.l, 0.93),
          tenderer_name: fv(info.name, t, info.l),
          date: fv("2026-09-01", t, info.l, 0.9),
        }
      : {
          document: fv(false, t, null, 0.88),
          signature: fv(null, t, null, null),
          tenderer_name: fv(null, t, null, null),
          date: fv(null, t, null, null),
        },
  };

  // As backend/routes/checks.py builds Verdict.evidence: one citation per
  // checked field, cited with that field's value, so a boolean ("document
  // submitted") cites the plain page and a name cites its quote on the page.
  const evidence = (letter) => Object.values(fields[letter]).map((f) => f.page).filter(Boolean);

  const verdicts = {
    a: verdict(
      "A",
      ["offer_to_be_bound.submitted", "offer_to_be_bound.signed"],
      [checked("offer_to_be_bound.document", "pass"), checked("offer_to_be_bound.signature", "pass")],
      evidence("a")
    ),
    k: verdict(
      "B",
      ["contact_details.submitted", "contact_details.contact_person"],
      [
        checked("contact_details.document", "pass"),
        contactOk
          ? checked("contact_details.contact_person", "pass")
          : checked("contact_details.contact_person", "needs_review", "contact person is not visible; a reviewer confirms"),
      ],
      evidence("k")
    ),
    l: hasL
      ? verdict(
          "A",
          [
            "noncollusive_certificate.submitted",
            "noncollusive_certificate.signed",
            "noncollusive_certificate.tenderer_identified",
            "noncollusive_certificate.dated",
          ],
          [
            checked("noncollusive_certificate.document", "pass"),
            checked("noncollusive_certificate.signature", "pass"),
            checked("noncollusive_certificate.tenderer_name", "pass"),
            checked("noncollusive_certificate.date", "pass"),
          ],
          evidence("l")
        )
      : verdict(
          "A",
          [
            "noncollusive_certificate.submitted",
            "noncollusive_certificate.signed",
            "noncollusive_certificate.tenderer_identified",
            "noncollusive_certificate.dated",
          ],
          [
            checked(
              "noncollusive_certificate.document",
              "disqualified",
              "document is missing; the tender is not considered further (Part A)"
            ),
            checked("noncollusive_certificate.signature", "dormant"),
            checked("noncollusive_certificate.tenderer_name", "dormant"),
            checked("noncollusive_certificate.date", "dormant"),
          ],
          []
        ),
  };

  const items = Object.fromEntries(Object.entries(verdicts).map(([letter, v]) => [letter, v.outcome]));
  return {
    tenderer: t,
    run_id: `run-${t.slice(-1).toLowerCase()}-0001`,
    ruleset_version: RULESET_VERSION,
    fields,
    verdicts,
    stage1: { outcome: worstOf(Object.values(items)), items },
    stage2: null,
    trace: null,
    cost: { calls: 3, cache_hits: 0, usd: 0.0, waited_seconds: 0.0 },
    review_confirmed_by: null,
  };
}

export function job({ job_id, tenderer, state, done = 0, total = 3 }) {
  return {
    job_id,
    kind: "check",
    project: PID,
    tenderer,
    state,
    step: state === "done" ? null : "extract",
    progress: { done, total, unit: "items" },
    attempt: 1,
    error: null,
    ruleset_version: RULESET_VERSION,
    created_at: T0,
    updated_at: T0,
  };
}

export const events = [
  {
    id: 1,
    kind: "ruleset.confirmed",
    project: PID,
    subject: "v1",
    before: null,
    after: { version: RULESET_VERSION, status: "confirmed" },
    user: "nasi",
    reason: null,
    at: T0,
  },
];

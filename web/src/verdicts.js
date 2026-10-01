// Reading a BidResult: the per-stage rollup of a Verdict's checks, the
// order of the items, the join between checks and field values.

// CheckedField.field_id is the rule's field ("noncollusive_certificate.date");
// BidResult.fields[letter] is keyed by its last segment ("date").
export const fieldName = (fieldId) => fieldId.split(".").pop();

const STATUS_SEVERITY = { pass: 0, needs_review: 1, disqualified: 2 };

// The engine's overall status for one stage: the worst non-dormant check
// (dormant fields do not count against a tender as submitted, the same rule
// as Verdict.outcome), "pass" when nothing in this stage is outstanding.
// Recomputed here because Verdict.outcome spans both stages and each page
// shows only its own.
export function stageRollup(checks, stage) {
  const inStage = checks.filter((c) => (stage === "II" ? c.stage === "II" : c.stage !== "II"));
  const counts = { pass: 0, needs_review: 0, disqualified: 0, dormant: 0 };
  let worst = "pass";
  inStage.forEach((c) => {
    counts[c.status] = (counts[c.status] ?? 0) + 1;
    if (c.status !== "dormant" && (STATUS_SEVERITY[c.status] ?? 0) > (STATUS_SEVERITY[worst] ?? 0)) {
      worst = c.status;
    }
  });
  return { status: worst, counts, empty: inStage.length === 0 };
}

// An item's status on one stage's page, read the way stage_summary
// (app/checks/engine_bridge.py) reads it, so the page agrees with the bid list
// and the report: null when nothing was checked at that stage (a Stage II rule
// for a limit the tender doesn't set, say), "dormant" when everything there
// is, and "needs_review" at Stage I for an item the engine could not check.
export function stageStatus(verdict, stage) {
  if (!verdict) return null;
  const { status, counts, empty } = stageRollup(verdict.checks, stage);
  if (empty) {
    return stage !== "II" && verdict.checks.length === 0 && verdict.outcome === "needs_review" ? "needs_review" : null;
  }
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  return counts.dormant === total ? "dormant" : status;
}

// Where a citation's page sits, deduplicated: the engine cites a page once per
// field read on it, so one certificate page can appear four times.
// One citation per page, in first-cited order. Verdict.evidence cites a page
// once per checked field, and only a field read as text carries a quote (and a
// signed highlight), so the quoted citation of a page wins over a plain one.
export function uniqueCitations(citations) {
  const byPage = new Map();
  for (const c of citations ?? []) {
    const key = `${c.doc_id}:${c.page}`;
    const seen = byPage.get(key);
    if (!seen || (!seen.quote && c.quote)) byPage.set(key, c);
  }
  return [...byPage.values()];
}

// Problems first: a reviewer opens this page to find what fails, not to read
// fifteen passes. Unchecked items last; the schedule's letter order within
// each group.
const SORT_RANK = { disqualified: 0, needs_review: 1, pass: 2, dormant: 3 };
const UNCHECKED_RANK = 4;

export function sortProblemsFirst(items) {
  return [...items].sort(
    (a, b) =>
      (SORT_RANK[a.status] ?? UNCHECKED_RANK) - (SORT_RANK[b.status] ?? UNCHECKED_RANK) ||
      a.order - b.order
  );
}

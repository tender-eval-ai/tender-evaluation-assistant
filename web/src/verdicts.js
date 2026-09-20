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

// Where a citation's page sits, deduplicated: the engine cites a page once per
// field read on it, so one certificate page can appear four times.
export function uniqueCitations(citations) {
  const seen = new Set();
  return (citations ?? []).filter((c) => {
    const key = `${c.doc_id}:${c.page}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
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

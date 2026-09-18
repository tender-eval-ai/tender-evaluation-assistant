import { WarningIcon, CheckCircleIcon, CircleDotIcon } from "./Icons.jsx";

const VARIANTS = {
  DISQUALIFY: { label: "Disqualify if missing", tone: "crit", Icon: WarningIcon },
  DEEMED_DEFAULT: { label: "Deemed default if missing", tone: "warn", Icon: CircleDotIcon },
  AMBIGUOUS_NEEDS_HUMAN: { label: "Needs human review", tone: "pending", Icon: CircleDotIcon },
  PASS: { label: "Pass", tone: "good", Icon: CheckCircleIcon },
  FAIL: { label: "Fail", tone: "crit", Icon: WarningIcon },
  FLAG_FOR_REVIEW: { label: "Flag for review", tone: "warn", Icon: WarningIcon },
  POSSIBLE_MATCH_NEEDS_REVIEW: { label: "Possible match — needs review", tone: "warn", Icon: WarningIcon },

  // The engine's outcome vocabulary (Verdict.outcome, CheckedField.status).
  // The contract serves no labels for it, so the wording lives here.
  pass: { label: "Compliant", tone: "good", Icon: CheckCircleIcon },
  disqualified: { label: "Disqualifying", tone: "crit", Icon: WarningIcon },
  needs_review: { label: "Needs human review", tone: "warn", Icon: WarningIcon },
  dormant: { label: "Not yet required", tone: "pending", Icon: CircleDotIcon },

  // Tenderer-level status on the bid list, from BidResult.stage1.outcome
  // (VendorCompletenessList maps pass/disqualified onto these).
  complete: { label: "Complete", tone: "good", Icon: CheckCircleIcon },
  missing: { label: "Missing", tone: "crit", Icon: WarningIcon },
  not_checked: { label: "Not checked", tone: "pending", Icon: CircleDotIcon },

  // RuleSetItem.status (app/rulesets/schema.py ItemStatus) in the Rules window.
  verified: { label: "Verified", tone: "good", Icon: CheckCircleIcon },
  needs_input: { label: "Needs input", tone: "crit", Icon: WarningIcon },
  novel: { label: "Novel — approve the drafted rules", tone: "warn", Icon: CircleDotIcon },
  gap: { label: "Gap — no rule built", tone: "crit", Icon: WarningIcon },
  edited: { label: "Edited by a person", tone: "pending", Icon: CircleDotIcon },

  // Price Summary row status (pricing/price_summary_service.py)
  RANKED: { label: "Ranked", tone: "good", Icon: CheckCircleIcon },
  CANNOT_CALCULATE: { label: "Cannot be calculated", tone: "warn", Icon: WarningIcon },
  DISQUALIFIED: { label: "Disqualified — not considered further", tone: "crit", Icon: WarningIcon },
  NOT_EXTRACTED: { label: "Not yet extracted", tone: "pending", Icon: CircleDotIcon },
};

export default function Badge({ kind, compact = false, label: labelOverride }) {
  const variant = VARIANTS[kind] ?? { label: kind, tone: "pending", Icon: CircleDotIcon };
  const { Icon } = variant;
  const label = labelOverride ?? variant.label;

  if (compact) {
    return (
      <span className="inline-flex" title={label}>
        <Icon className={`badge-icon badge-icon-${variant.tone}`} />
        <span className="sr-only">{label}</span>
      </span>
    );
  }

  return (
    <span className={`badge badge-${variant.tone}`}>
      <Icon className="badge-icon-inline" />
      {label}
    </span>
  );
}

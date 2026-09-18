import { WarningIcon, CheckCircleIcon, CircleDotIcon } from "./Icons.jsx";

const VARIANTS = {
  DISQUALIFY: { label: "Disqualify if missing", tone: "crit", Icon: WarningIcon },
  DEEMED_DEFAULT: { label: "Deemed default if missing", tone: "warn", Icon: CircleDotIcon },
  AMBIGUOUS_NEEDS_HUMAN: { label: "Needs human review", tone: "pending", Icon: CircleDotIcon },
  PASS: { label: "Pass", tone: "good", Icon: CheckCircleIcon },
  FAIL: { label: "Fail", tone: "crit", Icon: WarningIcon },
  FLAG_FOR_REVIEW: { label: "Flag for review", tone: "warn", Icon: WarningIcon },
  POSSIBLE_MATCH_NEEDS_REVIEW: { label: "Possible match — needs review", tone: "warn", Icon: WarningIcon },

  // FieldResult.status vocabulary (validator/field_result.py) - Stage I/II
  // checker output (ValidationPanel). Label text here is a fallback only:
  // the authoritative copy lives in field_result.STATUS_LABELS, served via
  // GET /api/validator/status-labels and passed through the `label` prop so
  // the backend stays the single source of truth for this wording, same as
  // every citation string elsewhere in this app is served, not hand-copied.
  pass: { label: "Compliant", tone: "good", Icon: CheckCircleIcon },
  disqualified: { label: "Disqualifying", tone: "crit", Icon: WarningIcon },
  needs_review: { label: "Needs human review", tone: "warn", Icon: WarningIcon },
  dormant: { label: "Not yet required", tone: "pending", Icon: CircleDotIcon },

  // Vendor-level rollup status (get_vendor_completeness_summary) - one badge
  // per vendor row on the Completeness Check landing page, worst-of across
  // that vendor's own per-letter overall_status values.
  complete: { label: "Complete", tone: "good", Icon: CheckCircleIcon },
  missing: { label: "Missing", tone: "crit", Icon: WarningIcon },
  not_checked: { label: "Not checked", tone: "pending", Icon: CircleDotIcon },

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
    return <Icon className={`badge-icon badge-icon-${variant.tone}`} title={label} />;
  }

  return (
    <span className={`badge badge-${variant.tone}`}>
      <Icon className="badge-icon-inline" />
      {label}
    </span>
  );
}

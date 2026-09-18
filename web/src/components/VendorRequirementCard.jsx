import Badge from "./Badge.jsx";

const TIER = {
  A: { label: "Mandatory", dot: "bg-mandatory", stripe: "border-l-mandatory" },
  B: { label: "Rectifiable", dot: "bg-rectifiable", stripe: "border-l-rectifiable" },
  C: { label: "Discretionary", dot: "bg-discretionary", stripe: "border-l-discretionary" },
};

// Same layout as RequirementCard (Rules window) - same stripe/dot/tier
// treatment - plus the one thing that screen deliberately doesn't show: the
// item's status for this page's stage (Stage I Completeness vs Stage II
// Compliance), from the tenderer's Verdict.
export default function VendorRequirementCard({ item, status, isActive, onSelect }) {
  const tier = TIER[item.part] ?? TIER.C;

  return (
    <button
      type="button"
      data-letter={item.letter}
      data-status={status ?? "not_checked"}
      onClick={() => onSelect(item)}
      aria-pressed={isActive}
      className={`w-full text-left border border-border-soft border-l-2 ${tier.stripe} rounded-[4px] bg-card
        cursor-pointer transition-all px-2.5 py-1.5
        ${isActive ? "shadow-sm ring-1 ring-accent/25 border-border" : "hover:border-border"}
        focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2`}
    >
      <div className="flex items-center justify-between gap-2 mb-0.5">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <span className="font-mono text-xs font-semibold text-accent-strong">{item.displayId}</span>
          <span className="flex items-center gap-1">
            <span className={`w-1.5 h-1.5 rounded-full ${tier.dot}`} />
            <span className="text-xs text-ink-4">{tier.label}</span>
          </span>
        </div>
        {status ? (
          <Badge kind={status} compact />
        ) : (
          <span className="font-mono text-xs text-ink-4 shrink-0">not checked</span>
        )}
      </div>
      <p className="text-xs leading-4 text-ink-2 line-clamp-1">{item.title}</p>
    </button>
  );
}

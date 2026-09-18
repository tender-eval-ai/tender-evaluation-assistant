// The real pipeline from plan.md, rendered as the Figma design's compact
// segmented control rather than a row of wide banners, now the ONLY
// navigation (the TopNav tab bar was removed - every one of these 5 stages
// is a distinct screen, so a separate tab bar duplicated this exactly).
// Stage I completeness and Stage II compliance are now separate pages
// (window2/window2b) - they used to be one merged screen with two
// subsections, which live review found wasn't real separation.
// Every stage past the rules requires a confirmed rule set (POST /checks
// answers 409 unconfirmed_ruleset without one) - checking offers against
// rules nobody has confirmed is the thing this gate exists to prevent.
const STAGES = [
  { id: "rules", label: "RULES", built: true, window: "rules", requiresConfirmation: false },
  { id: "stage1", label: "STAGE I COMPLETENESS", built: true, window: "stage1", requiresConfirmation: true },
  { id: "stage2", label: "STAGE II COMPLIANCE", built: true, window: "stage2", requiresConfirmation: true },
  // Price summary, evaluation and reports are S4 routes.
  { id: "stage3", label: "SCORING", built: false, window: null, requiresConfirmation: true },
  { id: "report", label: "REPORT", built: false, window: null, requiresConfirmation: true },
];

const FILTERS = [
  { key: "all", label: "all" },
  { key: "A", label: "mandatory" },
  { key: "B", label: "rectifiable" },
  { key: "C", label: "discretionary" },
];

export default function PipelineStepper({
  tierFilter,
  onTierFilter,
  tierCounts,
  activeWindow,
  onSelectWindow,
  confirmed = false,
}) {
  const showFilter = Boolean(tierCounts && onTierFilter);

  return (
    <div className="h-11 bg-card border-b border-border flex items-center px-4 gap-4 shrink-0">
      <div className="flex items-center gap-0.5 border border-border rounded p-0.5 shrink-0">
        {STAGES.map((stage, i) => {
          const gated = stage.requiresConfirmation && !confirmed;
          const clickable = stage.built && stage.window && onSelectWindow && !gated;
          const isActive = stage.window && stage.window === activeWindow;
          const title = !stage.built
            ? "Not yet built"
            : gated
              ? "Confirm the rule set first"
              : undefined;
          return (
            <button
              key={stage.id}
              type="button"
              disabled={!clickable}
              title={title}
              onClick={clickable ? () => onSelectWindow(stage.window) : undefined}
              className={`px-3 py-1 text-xs font-medium rounded font-mono transition-colors ${
                isActive
                  ? "bg-navy text-white cursor-default"
                  : clickable
                    ? "text-ink-3 hover:text-ink-1 hover:bg-secondary cursor-pointer"
                    : "text-ink-3 opacity-55 cursor-not-allowed"
              }`}
            >
              {i + 1} · {stage.label}
            </button>
          );
        })}
      </div>

      {showFilter && (
        <div className="flex items-center gap-1 min-w-0">
          <span className="text-xs text-ink-4 mr-1 shrink-0">Filter:</span>
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => onTierFilter(f.key)}
              aria-pressed={tierFilter === f.key}
              className={`px-2 py-0.5 text-xs rounded border transition-colors cursor-pointer shrink-0
                focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 ${
                  tierFilter === f.key
                    ? "border-accent bg-accent-wash text-accent-strong font-medium"
                    : "border-transparent text-ink-3 hover:text-ink-2"
                }`}
            >
              {f.label} <span className="font-mono text-ink-4">{tierCounts[f.key] ?? 0}</span>
            </button>
          ))}
        </div>
      )}

      <div className="ml-auto flex items-center gap-3 shrink-0">
        <span className="text-xs text-ink-3 font-mono">
          {STAGES.find((s) => s.window === activeWindow)?.label ?? ""}
        </span>
      </div>
    </div>
  );
}

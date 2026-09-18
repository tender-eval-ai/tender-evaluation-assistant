import CollapsibleSection from "./CollapsibleSection.jsx";

const TIER = {
  A: { label: "Mandatory", cls: "text-mandatory border-mandatory/40" },
  B: { label: "Rectifiable", cls: "text-rectifiable border-rectifiable/40" },
  C: { label: "Discretionary", cls: "text-discretionary border-border" },
};

function CitationButton({ citation, onViewReference, label }) {
  return (
    <button
      type="button"
      onClick={() => onViewReference(citation, label)}
      className="flex items-center justify-between gap-2 px-2.5 py-2 border border-border-soft rounded
        bg-faint text-left w-full transition-colors cursor-pointer hover:border-border
        focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
    >
      <span className="text-xs text-ink-2 min-w-0 line-clamp-2">{citation.quote}</span>
      <span className="font-mono text-xs text-ink-4 shrink-0">p.{citation.page} →</span>
    </button>
  );
}

// One RuleSetItem: the schedule row it comes from (verbatim, with its
// citation), the clauses it points to, its notes and its rules.
export default function RequirementDetail({ item, onViewReference }) {
  if (!item) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-center text-xs text-ink-4">
        Select a requirement to see its full text, source page and rules.
      </div>
    );
  }

  const tier = TIER[item.part] ?? TIER.C;

  return (
    <div className="flex-1 overflow-y-auto p-4">
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="flex items-center gap-2 mb-1">
          <span className="font-mono text-sm font-bold text-accent-strong">{item.displayId}</span>
          <span className="font-mono text-xs text-ink-4">
            Part {item.part} · {item.status}
          </span>
        </div>
        <span className={`px-2 py-0.5 text-xs border rounded font-medium shrink-0 ${tier.cls}`}>{tier.label}</span>
      </div>

      <p className="text-sm leading-6 text-ink font-medium mb-3">{item.title}</p>

      <CollapsibleSection title="Schedule row" defaultOpen>
        <p className="text-sm leading-6 text-ink-2 border-l-2 border-border pl-3 mb-2">{item.citation.quote}</p>
        <CitationButton
          citation={item.citation}
          onViewReference={onViewReference}
          label={`(${item.letter}) — schedule row`}
        />
      </CollapsibleSection>

      {item.clauses?.length > 0 && (
        <CollapsibleSection title="Referenced clauses">
          <div className="flex flex-col gap-1">
            {item.clauses.map((c) => (
              <CitationButton
                key={`${c.file}-${c.page}-${c.node_id}`}
                citation={c}
                onViewReference={onViewReference}
                label={c.node_id ?? c.file}
              />
            ))}
          </div>
        </CollapsibleSection>
      )}

      {item.notes?.length > 0 && (
        <CollapsibleSection title="Notes">
          <ul className="list-disc list-outside pl-4 space-y-1">
            {item.notes.map((n, i) => (
              <li key={i} className="text-xs text-ink-2">
                <span className="font-mono text-ink-4">{n.kind} </span>
                {n.text}
              </li>
            ))}
          </ul>
        </CollapsibleSection>
      )}

      <CollapsibleSection title={`Rules · ${item.rules.length}`} defaultOpen>
        <div className="flex flex-col gap-1.5">
          {item.rules.map((r) => (
            <div key={r.id} className="p-2.5 border border-border-soft rounded bg-faint">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-ink-2">{r.id}</span>
                <span className="font-mono text-xs text-ink-4 shrink-0">
                  {r.check} · Stage {r.stage}
                </span>
              </div>
              <p className="text-xs text-ink-3 mt-1">
                {r.field}
                {r.depends_on?.length > 0 && <span className="text-ink-4"> · after {r.depends_on.join(", ")}</span>}
              </p>
              {r.note && <p className="text-xs text-ink-4 mt-1">{r.note}</p>}
            </div>
          ))}
        </div>
      </CollapsibleSection>
    </div>
  );
}

import CollapsibleSection from "./CollapsibleSection.jsx";

const TIER = {
  A: { label: "Mandatory", cls: "text-mandatory border-mandatory/40" },
  B: { label: "Rectifiable", cls: "text-rectifiable border-rectifiable/40" },
  C: { label: "Discretionary", cls: "text-discretionary border-border" },
};

// This pane's job is reviewing whether the *extraction* reads correctly
// (verbatim text, source, citations) - vendor-compliance status moved
// entirely to the Vendor Check screen. No per-item Confirmed/Rejected/
// Pending badge or buttons here anymore; the one remaining reviewer action
// for this schedule is the page-level "Confirm all requirements" button in
// Window1's list panel.
export default function RequirementDetail({ item, saving = false, onViewReference, onSetStatus }) {
  if (!item) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-center text-xs text-ink-4">
        Select a requirement to see its full text, source page and referenced clauses.
      </div>
    );
  }

  const tier = TIER[item.part] ?? TIER.C;

  return (
    <div className="flex-1 overflow-y-auto p-4">
      <div className="flex items-start justify-between gap-2 mb-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-mono text-sm font-bold text-accent-strong">{item.displayId}</span>
            {/* The public's own identity for this obligation - the key any
                reviewer decision is actually stored against. */}
            <span className="font-mono text-xs text-ink-4">
              Part {item.part} · item ({item.letter})
            </span>
          </div>
        </div>
        <span className={`px-2 py-0.5 text-xs border rounded font-medium shrink-0 ${tier.cls}`}>{tier.label}</span>
      </div>

      {item.summary && (
        <CollapsibleSection title="Summary · AI" defaultOpen>
          <p className="text-sm leading-6 text-ink font-medium">{item.summary}</p>
        </CollapsibleSection>
      )}

      <CollapsibleSection title={`Verbatim text · ${item.name.length} chars`} defaultOpen>
        <p className="text-sm leading-6 text-ink-2 border-l-2 border-border pl-3">{item.name}</p>
      </CollapsibleSection>

      <CollapsibleSection title="Source">
        <ul className="list-disc list-outside pl-4 space-y-1">
          <li className="text-xs text-ink-2">{item.source_page.source_file}</li>
          <li className="font-mono text-xs text-ink-3">
            Page {item.source_page.page_number} · Completeness Check Schedule, Part {item.part}
          </li>
        </ul>
        <button
          type="button"
          onClick={() => onViewReference([item.source_page], `${item.id} — where this item appears`)}
          className="mt-2 font-mono text-xs text-accent hover:underline cursor-pointer"
        >
          &#8594; View source page
        </button>
      </CollapsibleSection>

      {item.references_paragraphs.length > 0 && (
        <CollapsibleSection title="Referenced clauses">
          <div className="flex flex-col gap-1">
            {item.references_paragraphs.map((ref) => {
              const resolved = ref.pages.length > 0;
              return (
                <button
                  type="button"
                  key={ref.descriptor}
                  disabled={!resolved}
                  onClick={() => onViewReference(ref.pages, ref.descriptor)}
                  className={`flex items-center justify-between gap-2 px-2.5 py-2 border border-border-soft rounded
                    bg-faint text-left w-full transition-colors
                    ${resolved ? "cursor-pointer hover:border-border" : "cursor-not-allowed opacity-60"}
                    focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2`}
                >
                  <span className="font-mono text-xs font-medium text-accent-strong min-w-0">{ref.descriptor}</span>
                  <span className="font-mono text-xs text-ink-4 shrink-0">
                    {resolved ? `p.${ref.pages[0].page_number} →` : "unresolved"}
                  </span>
                </button>
              );
            })}
          </div>
        </CollapsibleSection>
      )}

      {/* The two roles are stated separately on purpose: the requirement itself is
          parsed deterministically, and only the summary is model-generated. The
          verbatim text above remains the source of truth either way. */}
      <CollapsibleSection title="Method">
        <p className="text-xs text-ink-3 leading-5">
          <span className="text-ink-2 font-medium">Extraction is deterministic</span> — a parse of the tender's own
          Completeness Check Schedule, not an LLM reading of prose. No confidence score: this path has no inference
          step.
          <span className="block mt-1">
            <span className="text-ink-2 font-medium">AI is used for the summary only.</span> Verify it against the
            verbatim text above before relying on it.
          </span>
        </p>
      </CollapsibleSection>

      <CollapsibleSection title="Reviewer note">
        <textarea
          key={`${item.id}-note`}
          defaultValue={item.notes ?? ""}
          onBlur={(event) => {
            const next = event.target.value.trim();
            // Preserves whatever status the item currently has (set in bulk by
            // "Confirm all requirements") - this field only ever updates notes.
            if (next !== (item.notes ?? "")) onSetStatus(item.id, item.status ?? "pending", { notes: next });
          }}
          placeholder="Recorded in the audit log…"
          disabled={saving}
          className="w-full text-xs leading-5 p-2 rounded border border-border bg-card text-ink resize-y min-h-[54px]
            focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-1 disabled:opacity-60"
        />
      </CollapsibleSection>
    </div>
  );
}

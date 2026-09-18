import { useEffect, useMemo, useState } from "react";
import { confirmRuleset, getRuleset, listDocuments } from "../api.js";
import { tenderPage } from "../citations.js";
import DocumentViewer from "../components/DocumentViewer.jsx";
import RequirementCard from "../components/RequirementCard.jsx";
import RequirementDetail from "../components/RequirementDetail.jsx";

const TIER_LABEL = { A: "Mandatory", B: "Rectifiable", C: "Discretionary" };
const PART_NOTE = {
  A: "Missing = not considered further",
  B: "Missing = may be requested before disqualifying",
  C: "Discretionary",
};

// The Rules window at S2: the project's rule set (GET /ruleset, the latest
// draft, else the latest confirmed version) read against the tender. Item
// editing, diffs and gaps arrive with the rule builder at S3; S2 has the
// whole-draft editor (PUT /ruleset/draft) and confirmation.
export default function RulesWindow({ projectId, tierFilter = "all", onCountsChange, onConfirmed }) {
  const [ruleset, setRuleset] = useState(null);
  const [documents, setDocuments] = useState(null);
  const [error, setError] = useState(null);
  const [activeLetter, setActiveLetter] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [viewer, setViewer] = useState({ file: null, label: null, pages: [], focus: null });

  useEffect(() => {
    let cancelled = false;
    setRuleset(null);
    setError(null);
    Promise.all([getRuleset(projectId), listDocuments(projectId)])
      .then(([rs, docs]) => {
        if (cancelled) return;
        setRuleset(rs);
        setDocuments(docs);
        setActiveLetter(rs.items[0]?.letter ?? null);
      })
      .catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const items = useMemo(
    () => (ruleset?.items ?? []).map((item) => ({ ...item, id: item.letter, displayId: `(${item.letter})` })),
    [ruleset]
  );
  const active = items.find((i) => i.letter === activeLetter) ?? null;

  const tierCounts = useMemo(() => {
    const c = { all: items.length, A: 0, B: 0, C: 0 };
    items.forEach((i) => {
      if (c[i.part] !== undefined) c[i.part]++;
    });
    return c;
  }, [items]);

  const countsKey = `${tierCounts.all}-${tierCounts.A}-${tierCounts.B}-${tierCounts.C}`;
  useEffect(() => {
    if (onCountsChange) onCountsChange(tierCounts);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [countsKey]);

  function viewCitation(citation, label) {
    if (!citation || !documents) return;
    tenderPage(projectId, documents, citation)
      .then((page) => setViewer({ file: page.file, label, pages: [page], focus: page.pageNumber }))
      .catch((err) => setSaveError(err.message));
  }

  useEffect(() => {
    if (active && documents) viewCitation(active.citation, `(${active.letter}) — schedule row`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.letter, documents]);

  function handleConfirm() {
    setConfirming(true);
    setSaveError(null);
    confirmRuleset(projectId)
      .then((rs) => {
        setRuleset(rs);
        onConfirmed?.(rs);
      })
      .catch((err) =>
        setSaveError(
          err.code === "self_approval"
            ? "You edited this draft last; another person confirms it."
            : `Could not confirm: ${err.message}`
        )
      )
      .finally(() => setConfirming(false));
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-mandatory p-10 text-center">
        Failed to load: {error}
      </div>
    );
  }
  if (!ruleset) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-ink-3 p-10 text-center">
        Loading the rule set…
      </div>
    );
  }

  const visible = tierFilter === "all" ? items : items.filter((i) => i.part === tierFilter);
  const parts = ["A", "B", "C"].filter((p) => visible.some((i) => i.part === p));

  return (
    <div className="flex-1 flex overflow-hidden min-h-0">
      {/* LEFT — source document */}
      <div className="w-[30%] min-w-0 border-r border-border flex flex-col overflow-hidden bg-bg">
        <div className="px-3 py-2.5 border-b border-border bg-card shrink-0">
          <p className="font-mono text-xs text-ink-4 uppercase tracking-wider">Source document</p>
          <p className="text-xs font-semibold text-accent-strong truncate mt-0.5">{viewer.file ?? "—"}</p>
          <p className="text-xs text-ink-4 truncate">{viewer.label ?? ""}</p>
        </div>
        <DocumentViewer
          pages={viewer.pages}
          focusPage={viewer.focus}
          emptyLabel="Select a requirement to see its source page."
        />
      </div>

      {/* CENTRE — the rule set's items */}
      <div className="w-[38%] min-w-0 border-r border-border flex flex-col overflow-hidden bg-card">
        <div className="px-3 py-2.5 border-b border-border bg-bg shrink-0">
          <p className="font-mono text-xs text-ink-4 uppercase tracking-wider mb-1.5">
            Rule set v{ruleset.version} · {ruleset.status} · {items.length} item{items.length === 1 ? "" : "s"}
          </p>
          {ruleset.status === "confirmed" ? (
            <p className="font-mono text-xs text-ok">
              ✓ Confirmed by {ruleset.confirmed_by}
              {ruleset.confirmed_at ? ` · ${new Date(ruleset.confirmed_at).toLocaleString()}` : ""}
            </p>
          ) : (
            <button
              type="button"
              disabled={confirming}
              onClick={handleConfirm}
              className="px-2.5 py-1 text-xs font-mono font-medium rounded border border-accent
                bg-accent-wash text-accent-strong hover:bg-accent hover:text-white transition-colors
                cursor-pointer disabled:opacity-50 disabled:cursor-wait"
            >
              {confirming ? "confirming…" : "✓ Confirm the rule set"}
            </button>
          )}
        </div>
        <div className="flex-1 overflow-y-auto p-2.5 flex flex-col gap-1.5">
          {parts.map((part) => (
            <div key={part} className="flex flex-col gap-1.5">
              <div className="flex items-baseline gap-2 pt-1">
                <span className="font-mono text-xs font-semibold uppercase tracking-wider text-ink-3">
                  {TIER_LABEL[part] ?? part}
                </span>
                <span className="text-xs text-ink-4 truncate">{PART_NOTE[part]}</span>
              </div>
              {visible
                .filter((i) => i.part === part)
                .map((item) => (
                  <RequirementCard
                    key={item.id}
                    item={item}
                    isActive={item.letter === activeLetter}
                    onSelect={(i) => setActiveLetter(i.letter)}
                  />
                ))}
            </div>
          ))}
        </div>
      </div>

      {/* RIGHT — the item's rules */}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden bg-card">
        <div className="px-3 py-2.5 border-b border-border bg-bg shrink-0">
          <p className="font-mono text-xs text-ink-4 uppercase tracking-wider">Requirement detail</p>
        </div>
        <RequirementDetail item={active} onViewReference={viewCitation} />
        {saveError && (
          <p className="px-3 py-2 border-t border-border bg-mandatory-wash text-xs text-mandatory shrink-0">
            {saveError}
          </p>
        )}
      </div>
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import {
  getStage1CompletenessChecklist,
  getStage1ItemSummaries,
  getStage1Rtm,
  listTenderPages,
  postConfirmAllRequirements,
  postStage1Decision,
  tenderDocumentPageImageUrl,
} from "../api.js";
import DocumentViewer from "../components/DocumentViewer.jsx";
import RequirementCard from "../components/RequirementCard.jsx";
import RequirementDetail from "../components/RequirementDetail.jsx";

const TIER_LABEL = { A: "Mandatory", B: "Rectifiable", C: "Discretionary" };

export default function Window1({
  tenderId,
  tierFilter = "all",
  onCountsChange,
  confirmation = { confirmed: false, reviewer: null, confirmed_at: null },
  onConfirmationChange,
}) {
  const [parts, setParts] = useState(null);
  const [tenderPages, setTenderPages] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeId, setActiveId] = useState(null);
  // Server-owned state: notes and the confirmed summary come from the RTM
  // store, so a reload shows what was actually recorded rather than anything
  // held only in this component. Per-item status is no longer surfaced in
  // this UI (see `confirmation` below) but still lives on each row - the
  // reviewer note save path still needs it to avoid clobbering it.
  const [rtm, setRtm] = useState({});
  const [confirmingAll, setConfirmingAll] = useState(false);
  const [saving, setSaving] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const [viewerFile, setViewerFile] = useState(null);
  const [focusPage, setFocusPage] = useState(null);
  const [focusBox, setFocusBox] = useState(null);
  const [viewerLabel, setViewerLabel] = useState(null);

  function jumpTo(sourceFile, pageNumber, box, label) {
    setViewerFile(sourceFile);
    setFocusPage(pageNumber);
    setFocusBox(box ?? null);
    setViewerLabel(label);
  }

  // No refresh path by design: extraction is deterministic (same documents + same
  // pinned rule version produce identical output, context.md §7.9), and re-deriving
  // the list underneath a reviewer's recorded decisions would silently invalidate
  // them. Re-extraction is an ops action, not a review-UI affordance.
  function load() {
    setLoading(true);
    setError(null);
    Promise.all([getStage1CompletenessChecklist(tenderId), listTenderPages(tenderId)])
      .then(([loadedParts, pages]) => {
        setParts(loadedParts);
        setTenderPages(pages);
        const first = loadedParts.find((p) => p.items.length > 0)?.items[0];
        if (first) {
          setActiveId(`${first.part}.${first.letter}`);
          jumpTo(
            first.source_page.source_file,
            first.source_page.page_number,
            first.source_page.box,
            `Completeness Check Schedule, Part ${first.part}`
          );
        }
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenderId]);

  // Two fetches on purpose. The RTM read is fast (cached summaries only) so
  // recorded decisions appear immediately; the summaries endpoint may generate on
  // a cold cache, so it runs behind and re-syncs when it lands. Rows show verbatim
  // text meanwhile and say so.
  useEffect(() => {
    let cancelled = false;
    setRtm({});
    setSaveError(null);
    getStage1Rtm(tenderId)
      .then((rows) => {
        if (!cancelled) setRtm(rows ?? {});
        return getStage1ItemSummaries(tenderId);
      })
      .then(() => (cancelled ? null : getStage1Rtm(tenderId)))
      .then((rows) => {
        if (!cancelled && rows) setRtm(rows);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [tenderId]);

  // `id` stays part+letter - the public's own identifier in the schedule, and
  // the key reviewer decisions are stored against. `displayId` (REQ-001…) is a
  // presentation label derived from position; it is deliberately NOT the key,
  // since positional numbering would shift if the schedule ever changed.
  const items = useMemo(() => {
    if (!parts) return [];
    let n = 0;
    return parts.flatMap((part) =>
      part.items.map((item) => {
        const id = `${item.part}.${item.letter}`;
        n += 1;
        const stored = rtm[id];
        return {
          ...item,
          id,
          displayId: `REQ-${String(n).padStart(3, "0")}`,
          status: stored?.status ?? "pending",
          summary: stored?.summary,
          reviewer: stored?.reviewer,
          decidedAt: stored?.decided_at,
          notes: stored?.notes,
        };
      })
    );
  }, [parts, rtm]);

  const active = items.find((i) => i.id === activeId) ?? null;

  const tierCounts = useMemo(() => {
    const c = { all: items.length, A: 0, B: 0, C: 0 };
    items.forEach((i) => {
      if (c[i.part] !== undefined) c[i.part]++;
    });
    return c;
  }, [items]);

  // Counts are derived here (this is where the data lives) but rendered in the
  // stage bar, so hand them upward. Only fires when the values actually change.
  const countsKey = `${tierCounts.all}-${tierCounts.A}-${tierCounts.B}-${tierCounts.C}`;
  useEffect(() => {
    if (onCountsChange) onCountsChange(tierCounts);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [countsKey]);

  const visible = tierFilter === "all" ? items : items.filter((i) => i.part === tierFilter);

  function handleSelect(item) {
    setActiveId(item.id);
    if (item.source_page) {
      jumpTo(item.source_page.source_file, item.source_page.page_number, item.source_page.box, `${item.id} — source`);
    }
  }

  // Writes go to the server first; local state is replaced with whatever the
  // store actually recorded, so the panel can never show a decision that was not
  // persisted. Failures surface rather than silently reverting.
  function handleSetStatus(id, status, { notes, summary } = {}) {
    setSaving(id);
    setSaveError(null);
    postStage1Decision(tenderId, id, { status, notes, summary })
      .then((row) => setRtm((prev) => ({ ...prev, [id]: row })))
      .catch((err) => setSaveError(`Could not save decision: ${err.message}`))
      .finally(() => setSaving(null));
  }

  function handleViewReference(pageRefs, label) {
    if (!pageRefs || pageRefs.length === 0) return;
    const t = pageRefs[0];
    jumpTo(t.source_file, t.page_number, t.box, label);
  }

  function handleConfirmAll() {
    setConfirmingAll(true);
    setSaveError(null);
    postConfirmAllRequirements(tenderId)
      .then(onConfirmationChange)
      .catch((err) => setSaveError(`Could not confirm: ${err.message}`))
      .finally(() => setConfirmingAll(false));
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-ink-3 p-10 text-center">
        Reading the Completeness Check Schedule from the real tender documents…
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-mandatory p-10 text-center">
        Failed to load: {error}
      </div>
    );
  }

  const viewerPages = (tenderPages ?? [])
    .filter((p) => p.source_file === viewerFile)
    .map((p) => ({
      url: tenderDocumentPageImageUrl(tenderId, p.source_file, p.page_number),
      label: `${p.source_file}, p.${p.page_number}`,
      pageNumber: p.page_number,
      box: p.page_number === focusPage ? focusBox : null,
    }));

  return (
    <div className="flex-1 flex overflow-hidden min-h-0">
      {/* LEFT — source document */}
      <div className="w-[30%] min-w-0 border-r border-border flex flex-col overflow-hidden bg-bg">
        <div className="px-3 py-2.5 border-b border-border bg-card shrink-0">
          <p className="font-mono text-xs text-ink-4 uppercase tracking-wider">Source document</p>
          <p className="text-xs font-semibold text-accent-strong truncate mt-0.5">{viewerFile ?? "—"}</p>
          <p className="text-xs text-ink-4 truncate">{viewerLabel ?? ""}</p>
        </div>
        <DocumentViewer
          pages={viewerPages}
          focusPage={focusPage}
          emptyLabel="Select a requirement to see its source page."
        />
      </div>

      {/* CENTRE — requirements list */}
      <div className="w-[38%] min-w-0 border-r border-border flex flex-col overflow-hidden bg-card">
        <div className="px-3 py-2.5 border-b border-border bg-bg shrink-0">
          <p className="font-mono text-xs text-ink-4 uppercase tracking-wider mb-1.5">
            Completeness Check Schedule · {items.length} requirements
          </p>
          {confirmation.confirmed ? (
            <p className="font-mono text-xs text-ok">
              ✓ Confirmed by {confirmation.reviewer}
              {confirmation.confirmed_at ? ` · ${new Date(confirmation.confirmed_at).toLocaleString()}` : ""}
            </p>
          ) : (
            // Bordered/filled, not a bare text link: this is the mandatory
            // gate for the rest of the pipeline now, not an optional aside.
            <button
              type="button"
              disabled={confirmingAll}
              onClick={handleConfirmAll}
              className="px-2.5 py-1 text-xs font-mono font-medium rounded border border-accent
                bg-accent-wash text-accent-strong hover:bg-accent hover:text-white transition-colors
                cursor-pointer disabled:opacity-50 disabled:cursor-wait"
            >
              {confirmingAll ? "confirming…" : "✓ Confirm all requirements"}
            </button>
          )}
        </div>
        <div className="flex-1 overflow-y-auto p-2.5 flex flex-col gap-1.5">
          {parts.map((part) => {
            const group = visible.filter((i) => i.part === part.part);
            if (group.length === 0) return null;
            return (
              <div key={part.part} className="flex flex-col gap-1.5">
                <div className="flex items-baseline gap-2 pt-1">
                  <span className="font-mono text-xs font-semibold uppercase tracking-wider text-ink-3">
                    {TIER_LABEL[part.part] ?? part.part}
                  </span>
                  <span className="text-xs text-ink-4 truncate">{part.consequence_rule}</span>
                </div>
                {group.map((item) => (
                  <RequirementCard key={item.id} item={item} isActive={item.id === activeId} onSelect={handleSelect} />
                ))}
              </div>
            );
          })}
        </div>
      </div>

      {/* RIGHT — requirement detail */}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden bg-card">
        <div className="px-3 py-2.5 border-b border-border bg-bg shrink-0">
          <p className="font-mono text-xs text-ink-4 uppercase tracking-wider">Requirement detail</p>
        </div>
        <RequirementDetail
          item={active}
          saving={saving === active?.id}
          onViewReference={handleViewReference}
          onSetStatus={handleSetStatus}
        />
        {saveError && (
          <p className="px-3 py-2 border-t border-border bg-mandatory-wash text-xs text-mandatory shrink-0">
            {saveError}
          </p>
        )}
      </div>
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import {
  getStage1CompletenessChecklist,
  getStage1ItemSummaries,
  getStage1VendorCheckStatus,
  getValidatorStatusLabels,
  getVendorFieldReviews,
  postVendorFieldDecision,
  startStage1VendorCheck,
  vendorPageImageUrl,
} from "../api.js";
import DocumentViewer from "./DocumentViewer.jsx";
import JobProgress from "./JobProgress.jsx";
import VendorRequirementCard from "./VendorRequirementCard.jsx";
import VendorItemDetail, { stageRollup } from "./ValidationResults.jsx";

const TIER_LABEL = { A: "Mandatory", B: "Rectifiable", C: "Discretionary" };
const POLL_INTERVAL_MS = 2000;

// Letters whose OWN split fields carry at least one Stage II (essential-
// requirements adequacy) rule - checked per-letter against each checker's
// actual field ownership, not the whole rules file or a shared checker's
// blended output. Full exhaustive audit, all 15 letters, every rules file
// (2026-08-08 - context.md §19f):
//   (a) out of scope - separate Offer to be Bound flow, not this engine.
//   (b) YES - price_schedule_rules.json's only Stage II rule (unit_price_unit)
//       is on one_time_unit_price, which belongs to (b) after the
//       check_price_schedule_item_price/_dosage split.
//   (c) no - all of (c)'s own dosage fields are Stage I, no exceptions.
//   (d) no - all three of (d)'s essential fields are Stage I only.
//   (e) YES - particulars_of_goods_schedule_rules.json's only Stage II rule
//       (packing_plant_net_weight_range) is on packing_plant_net_weight_kg,
//       which belongs to (e).
//   (f) YES - information_schedule_rules_stage2.json's 6 Stage II rules
//       (iso_certificate, safety_data_sheet, product_specifications,
//       evaluation_report, event_disclosure_box, test_report_submission)
//       are all (f)'s own fields.
//   (g) YES - tender_sample_plant_trial_rules.json has 3 Stage II rules
//       (tender_sample x2, plant_trial).
//   (h) no - certification_track_record_rules.json has zero Stage II rules.
//   (i) no - manufacturer_letter_of_intent_rules.json has zero.
//   (j) no - board_resolution_extract (its only field) has no Stage II rule
//       anywhere; it only ever appeared here because it used to share (f)'s
//       UNSPLIT checker output (fixed via
//       check_information_schedule_board_resolution, plan.md 2026-08-08).
//   (k) no - appendix_contact_details_rules.json has zero.
//   (l) no - noncollusive_tendering_certificate_rules.json has zero.
//   (m) no - price_schedule_parts_c_d_rules.json has zero.
//   (n) YES - compliance_schedule_rules.json has 7 Stage II rules across
//       Parts A-D.
//   (o) no - contract_deposit_method_rules.json has zero.
// Also grepped every checker file for a dynamic per-vendor stage-bump
// pattern (the kind that makes (b)/(e) conditional) - only those same two
// exist anywhere in this codebase; everything else's Stage II eligibility
// is exactly what its rules file's own static `stage` tagging says.
const STAGE_II_LETTERS = new Set(["b", "e", "f", "g", "n"]);

// The shared shell behind both the Stage I Completeness and Stage II
// Compliance pages - same 3-pane layout as the Requirements tab (source
// viewer | item list | item detail), same card-list middle panel, same
// CollapsibleSection detail pattern - only the `stage` prop and which items
// are listed differ between the two. Both pages read/drive the SAME
// background job (resolve→extract→check runs once per vendor, covers both
// stages at once), so running it from either page shows results on both.
export default function StageResultsWindow({ tenderId, vendorId, stage, title }) {
  const [parts, setParts] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeId, setActiveId] = useState(null);
  const [job, setJob] = useState({ status: "not_started", progress: null, result: null, error: null });
  const [statusLabels, setStatusLabels] = useState({});
  const [fieldReviews, setFieldReviews] = useState({});
  const [summaries, setSummaries] = useState({});
  const [viewerFile, setViewerFile] = useState(null);
  const [viewerPages, setViewerPages] = useState([]);
  const [viewerLabel, setViewerLabel] = useState(null);
  const [focusPage, setFocusPage] = useState(null);
  const pollRef = useRef(null);

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function pollUntilDone() {
    stopPolling();
    pollRef.current = setInterval(() => {
      getStage1VendorCheckStatus(tenderId, vendorId).then((status) => {
        setJob(status);
        if (status.status === "done" || status.status === "error") stopPolling();
      });
    }, POLL_INTERVAL_MS);
  }

  function runCheck(refresh = false) {
    startStage1VendorCheck(tenderId, vendorId, { refresh }).then((status) => {
      setJob(status);
      if (status.status === "running") pollUntilDone();
    });
  }

  useEffect(() => {
    setLoading(true);
    setError(null);
    getStage1CompletenessChecklist(tenderId)
      .then((loadedParts) => {
        setParts(loadedParts);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [tenderId]);

  useEffect(() => {
    getValidatorStatusLabels().then(setStatusLabels).catch(() => {});
  }, []);

  // Same short AI-generated labels the Requirements tab (Window1) shows,
  // fetched the same way - one call, cache-only-if-already-generated
  // (getStage1ItemSummaries triggers generation on a cold cache, same as
  // Window1's own fetch). Keyed by tenderId only, not vendorId: these are
  // requirement-text labels, not vendor-specific data, so they don't need
  // to reload when switching vendors. Falls back to the verbatim item.name
  // in VendorRequirementCard/VendorItemDetail while empty, same fallback
  // Window1's RequirementCard already uses.
  useEffect(() => {
    let cancelled = false;
    setSummaries({});
    getStage1ItemSummaries(tenderId).then((loaded) => {
      if (!cancelled) setSummaries(loaded ?? {});
    });
    return () => {
      cancelled = true;
    };
  }, [tenderId]);

  // Reviewer decisions are per (tenderId, vendorId), independent of the
  // check job's own result - reload whenever either changes, same as the
  // job-status effect below, but this state isn't polled: it only changes
  // when this reviewer (or another one, on a later visit) posts a decision.
  useEffect(() => {
    setFieldReviews({});
    getVendorFieldReviews(tenderId, vendorId)
      .then(setFieldReviews)
      .catch(() => {});
  }, [tenderId, vendorId]);

  // Both Stage I and Stage II pages share this handler (same field key
  // shape, `${letter}:${field_id}`) - a decision made on one page is
  // immediately visible switching to the other, same as the rollup counts.
  function handleFieldDecision(letter, fieldId, decision, note, computedStatus) {
    return postVendorFieldDecision(tenderId, vendorId, letter, fieldId, {
      decision,
      note,
      computedStatus,
    }).then((row) => {
      setFieldReviews((prev) => ({ ...prev, [`${letter}:${fieldId}`]: row }));
    });
  }

  // Picks up whatever the job already is (running/done/not_started) rather
  // than auto-starting - real extraction is costly, so kicking it off is an
  // explicit "Run check" click, not something that fires on tab load.
  useEffect(() => {
    getStage1VendorCheckStatus(tenderId, vendorId)
      .then((status) => {
        setJob(status);
        if (status.status === "running") pollUntilDone();
      })
      .catch(() => {});
    return stopPolling;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenderId, vendorId]);

  // `id` mirrors Window1's part+letter key and REQ-00N numbering so the same
  // item reads as the same item across the Requirements/Stage I/Stage II
  // screens. Numbering is computed over the FULL 15-item list before any
  // stage filtering, so REQ-014 (letter n) is REQ-014 on every page, not
  // renumbered down to whatever position it lands at on a shorter list.
  const allItems = useMemo(() => {
    if (!parts) return [];
    let n = 0;
    return parts.flatMap((part) =>
      part.items.map((item) => {
        const id = `${item.part}.${item.letter}`;
        n += 1;
        return { ...item, id, displayId: `REQ-${String(n).padStart(3, "0")}`, summary: summaries[id] };
      })
    );
  }, [parts, summaries]);

  const items = useMemo(
    () => (stage === "II" ? allItems.filter((i) => STAGE_II_LETTERS.has(i.letter)) : allItems),
    [allItems, stage]
  );

  useEffect(() => {
    if (items.length > 0 && !items.some((i) => i.id === activeId)) {
      setActiveId(items[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);

  const active = items.find((i) => i.id === activeId) ?? null;
  const activeCheckResult = active && job.result ? job.result[active.letter] : undefined;

  const overallCounts = useMemo(() => {
    if (!job.result) return null;
    const c = { pass: 0, needs_review: 0, disqualified: 0, dormant: 0 };
    items.forEach((i) => {
      const r = job.result[i.letter];
      if (r?.available) {
        const rollup = stageRollup(r.fields ?? [], stage);
        Object.keys(c).forEach((key) => {
          c[key] += rollup.counts[key] ?? 0;
        });
      }
    });
    return c;
  }, [job.result, items, stage]);

  function showPages(pageRefs, label) {
    if (!pageRefs || pageRefs.length === 0) return;
    setViewerFile(pageRefs[0].source_file);
    setViewerPages(
      pageRefs.map((p) => ({
        url: vendorPageImageUrl(vendorId, p.source_file, p.page_number),
        label: `${p.source_file}, p.${p.page_number}`,
        pageNumber: p.page_number,
        box: p.box ?? null,
      }))
    );
    setFocusPage(pageRefs[0].page_number);
    setViewerLabel(label);
  }

  function handleSelect(item) {
    setActiveId(item.id);
    const cr = job.result?.[item.letter];
    if (cr?.resolved_pages?.length > 0) {
      showPages(cr.resolved_pages, `${item.id} — vendor submission`);
    } else {
      setViewerFile(null);
      setViewerPages([]);
      setFocusPage(null);
      setViewerLabel(null);
    }
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-ink-3 p-10 text-center">
        Reading the Completeness Check Schedule…
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

  return (
    <div className="flex-1 flex overflow-hidden min-h-0">
      {/* LEFT — vendor source document */}
      <div className="w-[30%] min-w-0 border-r border-border flex flex-col overflow-hidden bg-bg">
        <div className="px-3 py-2.5 border-b border-border bg-card shrink-0">
          <p className="font-mono text-xs text-ink-4 uppercase tracking-wider">Vendor submission</p>
          <p className="text-xs font-semibold text-accent-strong truncate mt-0.5">{viewerFile ?? "—"}</p>
          <p className="text-xs text-ink-4 truncate">{viewerLabel ?? ""}</p>
        </div>
        <DocumentViewer
          pages={viewerPages}
          focusPage={focusPage}
          emptyLabel="Select a requirement to see where it was found in the vendor's submission."
        />
      </div>

      {/* CENTRE — requirements list */}
      <div className="w-[38%] min-w-0 border-r border-border flex flex-col overflow-hidden bg-card">
        <div className="px-3 py-2.5 border-b border-border bg-bg shrink-0">
          <p className="font-mono text-xs text-ink-4 uppercase tracking-wider mb-1.5">
            {title} · {items.length} requirement{items.length === 1 ? "" : "s"}
          </p>
          {job.status === "not_started" && (
            <button
              type="button"
              onClick={() => runCheck(false)}
              className="font-mono text-xs text-accent hover:underline cursor-pointer"
            >
              ▶ Run check
            </button>
          )}
          {job.status === "running" && <JobProgress progress={job.progress} />}
          {job.status === "error" && <p className="text-xs text-mandatory">Check failed: {job.error}</p>}
          {job.status === "done" && overallCounts && (
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-xs text-ink-3">
                {overallCounts.pass} pass · {overallCounts.needs_review} needs review · {overallCounts.disqualified}{" "}
                disqualifying · {overallCounts.dormant} dormant
              </span>
              <button
                type="button"
                onClick={() => runCheck(true)}
                className="font-mono text-xs text-accent hover:underline cursor-pointer shrink-0"
              >
                ↻ re-run
              </button>
            </div>
          )}
        </div>
        <div className="flex-1 overflow-y-auto p-2.5 flex flex-col gap-1.5">
          {parts.map((part) => {
            const group = items.filter((i) => i.part === part.part);
            if (group.length === 0) return null;
            return (
              <div key={part.part} className="flex flex-col gap-1.5">
                <div className="flex items-baseline gap-2 pt-1">
                  <span className="font-mono text-xs font-semibold uppercase tracking-wider text-ink-3">
                    {TIER_LABEL[part.part] ?? part.part}
                  </span>
                  {/* consequence_rule ("Missing = disqualified immediately", etc.)
                      describes Stage I presence/completeness consequences - the
                      Part A/B/C tier itself is still useful context on the Stage
                      II page (which schedule this item belongs to), but showing
                      "Missing = ..." text next to a Stage II item is misleading:
                      Stage II is about whether SUBMITTED content is adequate,
                      never about whether something is missing (that's Stage I's
                      own question, already settled by the time an item reaches
                      here). */}
                  {stage !== "II" && <span className="text-xs text-ink-4 truncate">{part.consequence_rule}</span>}
                </div>
                {group.map((item) => (
                  <VendorRequirementCard
                    key={item.id}
                    item={item}
                    checkResult={job.result?.[item.letter]}
                    stageFilter={stage}
                    isActive={item.id === activeId}
                    onSelect={handleSelect}
                  />
                ))}
              </div>
            );
          })}
        </div>
      </div>

      {/* RIGHT — item detail */}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden bg-card">
        <div className="px-3 py-2.5 border-b border-border bg-bg shrink-0">
          <p className="font-mono text-xs text-ink-4 uppercase tracking-wider">{title} detail</p>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          {!active ? (
            <div className="flex items-center justify-center p-8 text-center text-xs text-ink-4">
              Select a requirement to see what was checked against the vendor's submission.
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2 mb-3">
                <span className="font-mono text-sm font-bold text-accent-strong">{active.displayId}</span>
                <span className="font-mono text-xs text-ink-4">
                  Part {active.part} · item ({active.letter})
                </span>
              </div>
              <VendorItemDetail
                item={active}
                letter={active.letter}
                checkResult={activeCheckResult}
                statusLabels={statusLabels}
                stageFilter={stage}
                onViewReference={showPages}
                fieldReviews={fieldReviews}
                onFieldDecision={handleFieldDecision}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

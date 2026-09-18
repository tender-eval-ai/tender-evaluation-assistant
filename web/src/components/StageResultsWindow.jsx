import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getBidResult, getJob, getRuleset, listDocuments, startChecks } from "../api.js";
import { offerPage, tenderPage } from "../citations.js";
import DocumentViewer from "./DocumentViewer.jsx";
import JobProgress from "./JobProgress.jsx";
import VendorRequirementCard from "./VendorRequirementCard.jsx";
import VendorItemDetail from "./ValidationResults.jsx";
import { sortProblemsFirst, stageRollup, uniqueCitations } from "../verdicts.js";

const POLL_INTERVAL_MS = 2000;

// An item belongs on the Stage II page when one of its rules is a Stage II
// rule; on the Stage I page when one is Stage I (or it has no rules yet).
function inStage(item, verdict, stage) {
  const stages = new Set([
    ...(item?.rules ?? []).map((r) => r.stage ?? "I"),
    ...(verdict?.checks ?? []).map((c) => c.stage ?? "I"),
  ]);
  if (stages.size === 0) return stage === "I";
  return stages.has(stage);
}

// The Stage I Completeness and Stage II Compliance pages for one tenderer:
// the offer's cited page (left), the rule set's items with their verdicts
// (centre), the selected item's checks (right). Data: GET .../results
// (BidResult) and the rule set version it was computed against; a tenderer
// without a finished check gets POST /checks and a job to poll.
export default function StageResultsWindow({ projectId, tenderer, stage, title, pollMs = POLL_INTERVAL_MS }) {
  const [result, setResult] = useState(undefined); // undefined loading, null not checked
  const [ruleset, setRuleset] = useState(null);
  const [documents, setDocuments] = useState(null);
  const [error, setError] = useState(null);
  const [job, setJob] = useState(null);
  const [activeLetter, setActiveLetter] = useState(null);
  const [viewer, setViewer] = useState({ file: null, label: null, pages: [], focus: null });
  const pollRef = useRef(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  };

  const load = useCallback(async () => {
    setError(null);
    try {
      let loaded = null;
      try {
        loaded = await getBidResult(projectId, tenderer);
      } catch (err) {
        if (err.code !== "not_found") throw err;
      }
      // The items' titles and parts come from the rule set the result was
      // computed against, not whatever draft is newest.
      const rs = await getRuleset(projectId, loaded ? { version: loaded.ruleset_version } : {});
      setRuleset(rs);
      setResult(loaded);
    } catch (err) {
      setError(err.message);
      setResult(null);
    }
  }, [projectId, tenderer]);

  useEffect(() => {
    setResult(undefined);
    setJob(null);
    setActiveLetter(null);
    setViewer({ file: null, label: null, pages: [], focus: null });
    load();
    listDocuments(projectId).then(setDocuments).catch(() => {});
    return stopPolling;
  }, [projectId, tenderer, load]);

  function poll(jobId) {
    pollRef.current = setTimeout(async () => {
      try {
        const next = await getJob(projectId, jobId);
        setJob(next);
        if (next.state === "done") {
          stopPolling();
          await load();
        } else if (next.state === "failed" || next.state === "dead") {
          stopPolling();
        } else {
          poll(jobId);
        }
      } catch (err) {
        setError(err.message);
      }
    }, pollMs);
  }

  async function runCheck() {
    setError(null);
    try {
      const { job_ids } = await startChecks(projectId, [tenderer]);
      const jobId = job_ids[tenderer];
      setJob({ job_id: jobId, state: "queued", progress: {} });
      poll(jobId);
    } catch (err) {
      // 409 unconfirmed_ruleset: nothing to check against yet.
      setError(err.code === "unconfirmed_ruleset" ? "Confirm the rule set before running a check." : err.message);
    }
  }

  const items = useMemo(() => {
    if (!ruleset) return [];
    const verdicts = result?.verdicts ?? {};
    const byLetter = new Map((ruleset.items ?? []).map((it, i) => [it.letter, { ...it, order: i }]));
    // A verdict for an item the rule set does not list still shows.
    Object.keys(verdicts).forEach((letter) => {
      if (!byLetter.has(letter)) {
        byLetter.set(letter, { letter, title: `Item (${letter})`, part: verdicts[letter].part, order: 1000 });
      }
    });
    const list = [...byLetter.values()]
      .filter((it) => inStage(it, verdicts[it.letter], stage))
      .map((it) => {
        const verdict = verdicts[it.letter] ?? null;
        const rollup = verdict ? stageRollup(verdict.checks, stage) : null;
        return { ...it, id: it.letter, displayId: `(${it.letter})`, verdict, status: rollup?.status ?? null };
      });
    return sortProblemsFirst(list);
  }, [ruleset, result, stage]);

  const active = items.find((i) => i.letter === activeLetter) ?? null;

  const showCitations = useCallback(
    (citations, label) => {
      const cites = uniqueCitations(citations);
      if (cites.length === 0) {
        setViewer({ file: null, label: null, pages: [], focus: null });
        return;
      }
      // Each citation's signed image_url carries its own highlight, and its
      // box (when on a text layer) is drawn over the page.
      setViewer({
        file: cites[0].file,
        label,
        pages: cites.map((c) => offerPage(c)),
        focus: cites[0].page,
      });
    },
    []
  );

  function handleSelect(item) {
    setActiveLetter(item.letter);
  }

  // Selecting an item (or the first one on load) shows where it was read.
  useEffect(() => {
    if (items.length > 0 && !items.some((i) => i.letter === activeLetter)) {
      setActiveLetter(items[0].letter);
    }
  }, [items, activeLetter]);

  useEffect(() => {
    if (!active) return;
    showCitations(active.verdict?.evidence ?? [], `(${active.letter}) — ${tenderer}'s offer`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.letter, result]);

  function viewTender(citation) {
    tenderPage(projectId, documents, citation)
      .then((page) => setViewer({ file: page.file, label: "Tender document", pages: [page], focus: page.pageNumber }))
      .catch((err) => setError(err.message));
  }

  const overallCounts = useMemo(() => {
    if (!result) return null;
    const c = { pass: 0, needs_review: 0, disqualified: 0, dormant: 0 };
    items.forEach((i) => {
      if (i.verdict) {
        const rollup = stageRollup(i.verdict.checks, stage);
        Object.keys(c).forEach((key) => {
          c[key] += rollup.counts[key] ?? 0;
        });
      }
    });
    return c;
  }, [result, items, stage]);

  if (result === undefined) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-ink-3 p-10 text-center">
        Loading {tenderer}'s results…
      </div>
    );
  }

  const running = job && !["done", "failed", "dead"].includes(job.state);

  return (
    <div className="flex-1 flex overflow-hidden min-h-0">
      {/* LEFT — the offer page the verdict cites */}
      <div className="w-[30%] min-w-0 border-r border-border flex flex-col overflow-hidden bg-bg">
        <div className="px-3 py-2.5 border-b border-border bg-card shrink-0">
          <p className="font-mono text-xs text-ink-4 uppercase tracking-wider">Vendor submission</p>
          <p className="text-xs font-semibold text-accent-strong truncate mt-0.5">{viewer.file ?? "—"}</p>
          <p className="text-xs text-ink-4 truncate">{viewer.label ?? ""}</p>
        </div>
        <DocumentViewer
          pages={viewer.pages}
          focusPage={viewer.focus}
          emptyLabel="Select a requirement to see where it was found in the vendor's submission."
        />
      </div>

      {/* CENTRE — the rule set's items, problems first */}
      <div className="w-[38%] min-w-0 border-r border-border flex flex-col overflow-hidden bg-card">
        <div className="px-3 py-2.5 border-b border-border bg-bg shrink-0">
          <p className="font-mono text-xs text-ink-4 uppercase tracking-wider mb-1.5">
            {title} · {tenderer} · {items.length} requirement{items.length === 1 ? "" : "s"}
          </p>
          {error && <p className="text-xs text-mandatory mb-1">{error}</p>}
          {running ? (
            <JobProgress job={job} />
          ) : job?.state === "failed" || job?.state === "dead" ? (
            <p className="text-xs text-mandatory">Check failed: {job.error}</p>
          ) : !result ? (
            <button
              type="button"
              onClick={runCheck}
              className="font-mono text-xs text-accent hover:underline cursor-pointer"
            >
              ▶ Run check
            </button>
          ) : (
            overallCounts && (
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-ink-3">
                  {overallCounts.pass} pass · {overallCounts.needs_review} needs review ·{" "}
                  {overallCounts.disqualified} disqualifying · {overallCounts.dormant} dormant
                </span>
                <span className="font-mono text-xs text-ink-4 shrink-0">rule set v{result.ruleset_version}</span>
              </div>
            )
          )}
        </div>
        <div className="flex-1 overflow-y-auto p-2.5 flex flex-col gap-1.5" data-testid="requirements">
          {items.map((item) => (
            <VendorRequirementCard
              key={item.id}
              item={item}
              status={item.status}
              isActive={item.letter === activeLetter}
              onSelect={handleSelect}
            />
          ))}
        </div>
      </div>

      {/* RIGHT — the selected item's verdict */}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden bg-card">
        <div className="px-3 py-2.5 border-b border-border bg-bg shrink-0">
          <p className="font-mono text-xs text-ink-4 uppercase tracking-wider">{title} detail</p>
        </div>
        <div className="flex-1 overflow-y-auto p-4" data-testid="item-detail">
          {!active ? (
            <div className="flex items-center justify-center p-8 text-center text-xs text-ink-4">
              Select a requirement to see what was checked against the vendor's submission.
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2 mb-1">
                <span className="font-mono text-sm font-bold text-accent-strong">{active.displayId}</span>
                <span className="font-mono text-xs text-ink-4">
                  Part {active.part} · item ({active.letter})
                </span>
              </div>
              <VendorItemDetail
                item={active}
                verdict={active.verdict}
                values={result?.fields?.[active.letter]}
                stageFilter={stage}
                onViewCitation={(c) => showCitations([c], `(${active.letter}) — ${tenderer}'s offer, p.${c.page}`)}
                onViewTender={viewTender}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

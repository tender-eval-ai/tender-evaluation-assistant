import { useEffect, useMemo, useRef, useState } from "react";
import Badge from "./Badge.jsx";
import {
  getStage1VendorCheckAllStatus,
  getStage1VendorSummary,
  startStage1VendorCheckAll,
} from "../api.js";

// Landing page for the Completeness Check step - one row per real vendor
// (registry.vendors_for_tender, not a placeholder list), clicking through to
// the existing per-vendor StageResultsWindow detail page. Every real project
// today has exactly one vendor folder on disk, so this will show a single
// row until more vendor data exists - the rollup and navigation are real,
// not populated with fabricated demo rows.
const FILTERS = [
  { key: "all", label: "All" },
  { key: "missing", label: "missing" },
  { key: "needs_review", label: "review" },
  { key: "complete", label: "complete" },
];

const POLL_INTERVAL_MS = 2000;

function formatLastChecked(iso) {
  if (!iso) return "not checked yet";
  return new Date(iso).toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
}

export default function VendorCompletenessList({ tenderId, onSelectVendor }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [batch, setBatch] = useState({ status: "not_started", progress: null, results: {} });
  const pollRef = useRef(null);

  function loadSummary() {
    return getStage1VendorSummary(tenderId).then(setRows);
  }

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function pollBatchUntilDone() {
    stopPolling();
    pollRef.current = setInterval(() => {
      getStage1VendorCheckAllStatus(tenderId).then((status) => {
        setBatch(status);
        // Refresh rows as each vendor finishes, not just once at the very
        // end - a long batch (many vendors) should visibly progress on
        // screen, not look frozen until everything completes.
        loadSummary();
        if (status.status === "done") stopPolling();
      });
    }, POLL_INTERVAL_MS);
  }

  function runCheckAll(refresh = false) {
    startStage1VendorCheckAll(tenderId, { refresh }).then((status) => {
      setBatch(status);
      if (status.status === "running") pollBatchUntilDone();
    });
  }

  useEffect(() => {
    setRows(null);
    setError(null);
    setBatch({ status: "not_started", progress: null, results: {} });
    loadSummary().catch((err) => setError(err.message));
    // Pick up whatever the batch job already is (e.g. still running from
    // before a page refresh) rather than assuming it's idle.
    getStage1VendorCheckAllStatus(tenderId).then((status) => {
      setBatch(status);
      if (status.status === "running") pollBatchUntilDone();
    });
    return stopPolling;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenderId]);

  const filtered = useMemo(() => {
    if (!rows) return [];
    const term = search.trim().toLowerCase();
    return rows
      .filter((r) => filter === "all" || r.status === filter)
      .filter((r) => !term || r.name.toLowerCase().includes(term));
  }, [rows, filter, search]);

  const counts = useMemo(() => {
    if (!rows) return { all: 0, missing: 0, needs_review: 0, complete: 0 };
    return {
      all: rows.length,
      missing: rows.filter((r) => r.status === "missing").length,
      needs_review: rows.filter((r) => r.status === "needs_review").length,
      complete: rows.filter((r) => r.status === "complete").length,
    };
  }, [rows]);

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-mandatory p-10 text-center">
        Failed to load: {error}
      </div>
    );
  }
  if (!rows) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-ink-3 p-10 text-center">
        Loading vendors…
      </div>
    );
  }

  const batchRunning = batch.status === "running";

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-card">
      <div className="px-4 py-3 border-b border-border bg-bg shrink-0 flex flex-col gap-2.5">
        <div className="flex items-center gap-2.5">
          <input
            type="text"
            placeholder="Search vendors…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 px-2.5 py-1.5 text-xs border border-border-soft rounded bg-card text-ink-2
              focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
          />
          <span className="font-mono text-xs text-ink-4 shrink-0">
            {filtered.length} / {rows.length}
          </span>
          {batchRunning ? (
            <span className="font-mono text-xs text-accent shrink-0 whitespace-nowrap truncate max-w-[50%]">
              Checking {batch.progress?.completed ?? 0}/{batch.progress?.total ?? rows.length}
              {batch.progress?.in_progress?.length > 0
                ? ` — ${batch.progress.in_progress.map((v) => v.name).join(", ")}`
                : ""}
            </span>
          ) : (
            <button
              type="button"
              onClick={() => runCheckAll(false)}
              className="font-mono text-xs text-accent hover:underline cursor-pointer shrink-0 whitespace-nowrap"
            >
              ▶ Run check (all vendors)
            </button>
          )}
        </div>
        {batchRunning && (
          <div className="w-full h-1 bg-faint rounded overflow-hidden">
            <div
              className="h-full bg-accent transition-all"
              style={{
                width: `${Math.min(100, Math.round((100 * (batch.progress?.completed ?? 0)) / Math.max(batch.progress?.total ?? rows.length, 1)))}%`,
              }}
            />
          </div>
        )}
        <div className="flex items-center gap-1.5 flex-wrap font-mono text-xs">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={`px-2 py-1 rounded border cursor-pointer transition-colors ${
                filter === f.key
                  ? "border-accent text-accent-strong bg-faint"
                  : "border-border-soft text-ink-4 hover:text-ink-2"
              }`}
            >
              {f.label} {counts[f.key]}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <table className="w-full text-xs border-collapse">
          <thead className="sticky top-0 bg-bg border-b border-border z-10">
            <tr className="font-mono text-ink-4 uppercase tracking-wider">
              <th className="text-left px-4 py-2 font-medium">Vendor</th>
              <th className="text-left px-3 py-2 font-medium">Last checked</th>
              <th className="text-left px-3 py-2 font-medium">OK</th>
              <th className="text-left px-3 py-2 font-medium">Review</th>
              <th className="text-left px-3 py-2 font-medium">Missing</th>
              <th className="text-left px-3 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => (
              <tr
                key={row.vendor_id}
                onClick={() => onSelectVendor(row.vendor_id)}
                className="cursor-pointer border-b border-border-soft hover:bg-faint transition-colors"
              >
                <td className="px-4 py-2.5 font-medium text-accent-strong">{row.name}</td>
                <td className="px-3 py-2.5 text-ink-3 font-mono">{formatLastChecked(row.last_checked)}</td>
                <td className="px-3 py-2.5 font-mono text-ok">{row.checked ? row.ok : "—"}</td>
                <td className="px-3 py-2.5 font-mono text-rectifiable">{row.checked ? row.review : "—"}</td>
                <td className="px-3 py-2.5 font-mono text-mandatory">{row.checked ? row.missing : "—"}</td>
                <td className="px-3 py-2.5">
                  <Badge kind={row.status} />
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-ink-4">
                  No vendors match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

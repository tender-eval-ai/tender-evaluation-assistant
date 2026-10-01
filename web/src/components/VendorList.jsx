import { useEffect, useMemo, useRef, useState } from "react";
import Badge from "./Badge.jsx";
import { getBidResult, getJob, getProject, startChecks } from "../api.js";

// Landing page for the Stage I and Stage II steps: one row per tenderer with an
// uploaded offer (GET /projects/{pid} `bidders`), that stage's rollup from its
// BidResult (`stage1`, `stage2`), clicking through to that tenderer's
// StageResultsWindow. The contract has no per-project rollup route, so this is
// one results call per tenderer; a tenderer without a finished check shows
// "not checked".
const STAGES = {
  I: {
    summary: "stage1",
    rowStatus: { pass: "complete", dormant: "complete", needs_review: "needs_review", disqualified: "missing" },
    filters: [
      { key: "all", label: "All" },
      { key: "missing", label: "missing" },
      { key: "needs_review", label: "review" },
      { key: "complete", label: "complete" },
    ],
    columns: ["OK", "Review", "Missing"],
  },
  II: {
    summary: "stage2",
    rowStatus: { pass: "compliant", dormant: "compliant", needs_review: "needs_review", disqualified: "noncompliant" },
    filters: [
      { key: "all", label: "All" },
      { key: "noncompliant", label: "non-compliant" },
      { key: "needs_review", label: "review" },
      { key: "compliant", label: "compliant" },
    ],
    columns: ["Pass", "Review", "Fail"],
  },
};

const POLL_INTERVAL_MS = 2000;

async function loadRow(projectId, tenderer, stage) {
  const { summary, rowStatus } = STAGES[stage];
  try {
    const r = await getBidResult(projectId, tenderer);
    // stage2 is null when the rule set has nothing at Stage II.
    if (!r[summary]) {
      return { tenderer, checked: true, status: "nothing_to_check", pass: 0, review: 0, fail: 0,
               rulesetVersion: r.ruleset_version };
    }
    const outcomes = Object.values(r[summary].items);
    return {
      tenderer,
      checked: true,
      status: rowStatus[r[summary].outcome] ?? "needs_review",
      pass: outcomes.filter((o) => o === "pass").length,
      review: outcomes.filter((o) => o === "needs_review").length,
      fail: outcomes.filter((o) => o === "disqualified").length,
      rulesetVersion: r.ruleset_version,
      // Stage II still lists a tenderer Stage I put out, and says so.
      outAtStageI: stage === "II" && r.stage1.outcome === "disqualified",
    };
  } catch (err) {
    if (err.code !== "not_found") throw err;
    return { tenderer, checked: false, status: "not_checked" };
  }
}

export default function VendorList({ projectId, stage = "I", onSelectVendor, pollMs = POLL_INTERVAL_MS }) {
  const { filters, columns } = STAGES[stage];
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [jobs, setJobs] = useState({}); // tenderer -> Job
  const pollRef = useRef(null);

  async function loadRows() {
    const project = await getProject(projectId);
    const loaded = await Promise.all((project.bidders ?? []).map((t) => loadRow(projectId, t, stage)));
    setRows(loaded);
  }

  function stopPolling() {
    if (pollRef.current) {
      clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }

  function poll(jobIds) {
    pollRef.current = setTimeout(async () => {
      try {
        const entries = await Promise.all(Object.entries(jobIds).map(async ([t, id]) => [t, await getJob(projectId, id)]));
        setJobs(Object.fromEntries(entries));
        await loadRows();
        const pending = entries.filter(([, j]) => !["done", "failed", "dead"].includes(j.state));
        if (pending.length > 0) poll(Object.fromEntries(pending.map(([t, j]) => [t, j.job_id])));
        else stopPolling();
      } catch (err) {
        setError(err.message);
      }
    }, pollMs);
  }

  async function runCheckAll() {
    setError(null);
    try {
      const { job_ids } = await startChecks(projectId);
      setJobs(Object.fromEntries(Object.entries(job_ids).map(([t, id]) => [t, { job_id: id, state: "queued" }])));
      poll(job_ids);
    } catch (err) {
      setError(err.code === "unconfirmed_ruleset" ? "Confirm the rule set before running a check." : err.message);
    }
  }

  useEffect(() => {
    setRows(null);
    setError(null);
    loadRows().catch((err) => setError(err.message));
    return stopPolling;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, stage]);

  const filtered = useMemo(() => {
    if (!rows) return [];
    const term = search.trim().toLowerCase();
    return rows
      .filter((r) => filter === "all" || r.status === filter)
      .filter((r) => !term || r.tenderer.toLowerCase().includes(term));
  }, [rows, filter, search]);

  const counts = useMemo(
    () =>
      Object.fromEntries(
        filters.map((f) => [f.key, (rows ?? []).filter((r) => f.key === "all" || r.status === f.key).length])
      ),
    [rows, filters]
  );

  if (!rows) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-ink-3 p-10 text-center">
        {error ? <span className="text-mandatory">Failed to load: {error}</span> : "Loading tenderers…"}
      </div>
    );
  }

  const running = Object.values(jobs).filter((j) => !["done", "failed", "dead"].includes(j.state));

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-card">
      <div className="px-4 py-3 border-b border-border bg-bg shrink-0 flex flex-col gap-2.5">
        <div className="flex items-center gap-2.5">
          <input
            type="text"
            placeholder="Search tenderers…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 px-2.5 py-1.5 text-xs border border-border-soft rounded bg-card text-ink-2
              focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
          />
          <span className="font-mono text-xs text-ink-4 shrink-0">
            {filtered.length} / {rows.length}
          </span>
          {running.length > 0 ? (
            <span className="font-mono text-xs text-accent shrink-0 whitespace-nowrap">
              Checking {Object.keys(jobs).length - running.length}/{Object.keys(jobs).length}
            </span>
          ) : (
            <button
              type="button"
              onClick={runCheckAll}
              className="font-mono text-xs text-accent hover:underline cursor-pointer shrink-0 whitespace-nowrap"
            >
              ▶ Run check (all tenderers)
            </button>
          )}
        </div>
        {error && <p className="text-xs text-mandatory">{error}</p>}
        <div className="flex items-center gap-1.5 flex-wrap font-mono text-xs">
          {filters.map((f) => (
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
              <th className="text-left px-4 py-2 font-medium">Tenderer</th>
              <th className="text-left px-3 py-2 font-medium">Rule set</th>
              {columns.map((c) => (
                <th key={c} className="text-left px-3 py-2 font-medium">{c}</th>
              ))}
              <th className="text-left px-3 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => (
              <tr
                key={row.tenderer}
                onClick={() => onSelectVendor(row.tenderer)}
                className="cursor-pointer border-b border-border-soft hover:bg-faint transition-colors"
              >
                <td className="px-4 py-2.5 font-medium text-accent-strong">
                  {row.tenderer}
                  {row.outAtStageI && (
                    <span className="ml-2 font-mono font-normal text-mandatory">disqualified at Stage I</span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-ink-3 font-mono">{row.checked ? `v${row.rulesetVersion}` : "—"}</td>
                <td className="px-3 py-2.5 font-mono text-ok">{row.checked ? row.pass : "—"}</td>
                <td className="px-3 py-2.5 font-mono text-rectifiable">{row.checked ? row.review : "—"}</td>
                <td className="px-3 py-2.5 font-mono text-mandatory">{row.checked ? row.fail : "—"}</td>
                <td className="px-3 py-2.5">
                  <Badge kind={row.status} />
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-ink-4">
                  No tenderers match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

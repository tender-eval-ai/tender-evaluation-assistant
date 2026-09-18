const PHASE_LABEL = {
  starting: "Starting…",
  resolving_pages: "Finding which page(s) match each requirement",
  extracting: "Reading values off the vendor's submission",
  checking: "Checking against the rules",
};

export default function JobProgress({ progress }) {
  const phase = progress?.phase;
  const completed = progress?.completed ?? 0;
  const total = progress?.total ?? 1;
  const pct = Math.min(100, Math.round((completed / Math.max(total, 1)) * 100));

  return (
    <div className="job-progress">
      <p className="job-progress-label">{PHASE_LABEL[phase] ?? "Working…"}</p>
      <div className="job-progress-track">
        <div className="job-progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <p className="job-progress-count">
        {completed} of {total}
      </p>
      <p className="job-progress-note">
        This runs in the background — you can switch to the other tab or come back later and it'll still be here.
      </p>
    </div>
  );
}

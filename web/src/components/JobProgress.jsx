// A check job (contract `Job`): state, the step it is on, and
// progress {done, total, unit} (step names from app/checks/vendor_check.py).
const STEP_LABEL = {
  render: "Rendering the offer's pages",
  triage: "Labelling the offer's pages",
  resolve: "Finding which page(s) match each requirement",
  extract: "Reading values off the vendor's submission",
  verify: "Checking the values read against the pages",
  evaluate: "Checking against the rules",
};

export default function JobProgress({ job }) {
  const done = job?.progress?.done ?? 0;
  const total = job?.progress?.total ?? 0;
  const unit = job?.progress?.unit ?? "steps";
  const pct = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  // `paused` is in openapi.json's Job.state (not in api_contract.md's list);
  // its progress is {reason} instead of {done, total, unit}.
  const label =
    job?.state === "queued"
      ? "Queued…"
      : job?.state === "paused"
        ? `Paused: ${job.progress?.reason ?? "waiting"}`
        : (STEP_LABEL[job?.step] ?? "Working…");

  return (
    <div className="job-progress" role="status">
      <p className="job-progress-label">{label}</p>
      <div className="job-progress-track">
        <div className="job-progress-fill" style={{ width: `${pct}%` }} />
      </div>
      {total > 0 && (
        <p className="job-progress-count">
          {done} of {total} {unit}
        </p>
      )}
      <p className="job-progress-note">
        This runs in the background — you can switch to the other tab or come back later and it'll still be here.
      </p>
    </div>
  );
}

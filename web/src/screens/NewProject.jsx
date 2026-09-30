import { useEffect, useState } from "react";
import JobProgress from "../components/JobProgress.jsx";
import { buildRuleset, createProject, getJob, importCase, listInbox, uploadBid, uploadTender } from "../api.js";

// The front door (#132): a new project from one of the prepared synthetic cases, or,
// where this deployment takes uploads (a machine the client controls), from the
// tender's and the offers' own PDFs. Then the rule set is drafted, and the Rules
// window opens on the draft.
const QUICKSTART = "#quickstart";

export default function NewProject({ settings, onCreated, onCancel, pollMs = 2000 }) {
  const [cases, setCases] = useState(null);
  const [source, setSource] = useState("case");
  const [picked, setPicked] = useState(null);
  const [name, setName] = useState("");
  const [dataClass, setDataClass] = useState("confidential");
  const [tenderFiles, setTenderFiles] = useState([]);
  const [bidders, setBidders] = useState([{ name: "", files: [] }]);
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const uploads = settings?.uploads ?? false;
  const classes = settings?.data_classes ?? ["synthetic"];

  useEffect(() => {
    listInbox().then((c) => {
      setCases(c);
      if (c.length) setPicked(c[0].name);
    }).catch((err) => setError(err.message));
  }, []);

  const pickedCase = cases?.find((c) => c.name === picked);

  async function waitFor(pid, jobId) {
    for (;;) {
      const j = await getJob(pid, jobId);
      setJob(j);
      if (["done", "failed", "dead"].includes(j.state)) return j;
      await new Promise((resolve) => setTimeout(resolve, pollMs));
    }
  }

  async function submit(event) {
    event.preventDefault();
    const title = name.trim() || (source === "case" ? pickedCase?.title ?? picked : "");
    if (!title) return setError("Give the project a name.");
    if (source === "case" && !picked) return setError("Choose a case.");
    if (source === "upload") {
      if (!tenderFiles.length) return setError("Add the tender's PDFs.");
      if (bidders.some((b) => !b.name.trim() || !b.files.length)) return setError("Name every tenderer and add their PDFs.");
    }
    setError(null);
    setBusy(true);
    try {
      const project = await createProject(title, source === "case" ? "synthetic" : dataClass);
      if (source === "case") {
        await importCase(project.id, picked);
      } else {
        await uploadTender(project.id, tenderFiles);
        for (const b of bidders) await uploadBid(project.id, b.name.trim(), b.files);
      }
      const { job_id } = await buildRuleset(project.id);
      const done = await waitFor(project.id, job_id);
      if (done.state !== "done") throw new Error(`the rule-set build ${done.state}: ${done.error ?? "no reason given"}`);
      onCreated(project.id);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  const setBidder = (i, patch) => setBidders((all) => all.map((b, n) => (n === i ? { ...b, ...patch } : b)));

  if (busy && job) {
    return (
      <div className="new-project" data-testid="new-project-building">
        <h2>Drafting the rule set</h2>
        <JobProgress job={job} />
      </div>
    );
  }

  return (
    <form className="new-project" onSubmit={submit} aria-label="New project">
      <h2>New project</h2>
      <label className="new-project-field">
        Name
        <input type="text" value={name} onChange={(e) => setName(e.target.value)}
               placeholder={source === "case" && pickedCase ? pickedCase.title ?? pickedCase.name : "e.g. Supply of flocculants 2027"} />
      </label>

      <fieldset className="new-project-source">
        <legend>Start from</legend>
        <label>
          <input type="radio" name="source" checked={source === "case"} onChange={() => setSource("case")} />
          a prepared synthetic case
        </label>
        {source === "case" && (
          <div className="case-grid" role="radiogroup" aria-label="Synthetic cases">
            {cases === null && <p className="new-project-note">Loading the cases…</p>}
            {cases?.length === 0 && <p className="new-project-note">No prepared case on this server.</p>}
            {cases?.map((c) => (
              <button type="button" key={c.name} role="radio" aria-checked={picked === c.name}
                      className={`case-card${picked === c.name ? " case-card-picked" : ""}`}
                      onClick={() => setPicked(c.name)} data-testid={`case-${c.name}`}>
                <span className="case-card-title">{c.title ?? c.name}</span>
                <span className="case-card-meta">{c.tender_pdfs} tender documents · {c.bidders.length} offers</span>
                {c.summary && <span className="case-card-summary">{c.summary}</span>}
                {c.look_for?.length > 0 && (
                  <ul className="case-card-look">
                    {c.look_for.map((l) => <li key={l}>{l}</li>)}
                  </ul>
                )}
              </button>
            ))}
          </div>
        )}

        <label className={uploads ? "" : "new-project-disabled"}>
          <input type="radio" name="source" disabled={!uploads} checked={source === "upload"}
                 onChange={() => setSource("upload")} />
          my own PDFs
        </label>
        {!uploads && (
          <p className="new-project-note" data-testid="uploads-off">
            This hosted demo runs synthetic cases only. Real tenders stay on a machine you control:{" "}
            {settings?.source_url
              ? <a href={`${settings.source_url}${QUICKSTART}`} target="_blank" rel="noreferrer">run it yourself</a>
              : "run it yourself"}.
          </p>
        )}
        {uploads && source === "upload" && (
          <div className="new-project-upload">
            <label className="new-project-field">
              Data class
              <select value={dataClass} onChange={(e) => setDataClass(e.target.value)}>
                {classes.map((c) => <option key={c} value={c}>{c.replace("_", " ")}</option>)}
              </select>
            </label>
            <label className="new-project-field">
              Tender documents (PDF)
              <input type="file" accept="application/pdf,.pdf" multiple aria-label="Tender documents"
                     onChange={(e) => setTenderFiles([...e.target.files])} />
            </label>
            {bidders.map((b, i) => (
              <div className="new-project-bidder" key={i}>
                <input type="text" value={b.name} placeholder="Tenderer's name" aria-label={`Tenderer ${i + 1} name`}
                       onChange={(e) => setBidder(i, { name: e.target.value })} />
                <input type="file" accept="application/pdf,.pdf" multiple aria-label={`Tenderer ${i + 1} offer`}
                       onChange={(e) => setBidder(i, { files: [...e.target.files] })} />
              </div>
            ))}
            <button type="button" className="new-project-quiet" onClick={() => setBidders((all) => [...all, { name: "", files: [] }])}>
              + another tenderer
            </button>
          </div>
        )}
      </fieldset>

      {error && <p className="error" role="alert">{error}</p>}
      <div className="actions">
        <button type="submit" disabled={busy}>{busy ? "Creating…" : "Create and draft the rules"}</button>
        <button type="button" onClick={onCancel} disabled={busy}>Cancel</button>
      </div>
    </form>
  );
}

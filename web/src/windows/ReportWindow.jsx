import { useCallback, useEffect, useState } from "react";
import { downloadReport, getEvaluation, listReports } from "../api.js";

const TITLES = {
  "price_summary.docx": "Price Summary",
  "summary_list.docx": "Summary List",
  "evaluation_record.docx": "Detailed Evaluation Record",
};

const when = (iso) => (iso ? new Date(iso).toLocaleString("en-HK", { dateStyle: "medium", timeStyle: "short" }) : null);

// Hands a fetched file to the browser as a download. The object URL outlives the
// click for a while, as FileSaver does, because revoking it at once can cancel the
// download in some browsers.
function save(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 40_000);
}

// The Report window: the evaluation across tenderers, and the three .docx reports.
//
// A report is rendered fresh from the stored results every time it is downloaded.
// It is fetched like every other call, with the X-API-Key header a plain link cannot
// send, and saved from the Blob. `generated_at` is null until a report has been
// downloaded once, which is what the list shows; it is not a build step to wait for.
//
// The API refuses a report with 409 `review_pending` while any checked tenderer's
// review is unconfirmed. The evaluation already says who that is (`reviewed_by` is
// null), so the buttons wait and say why BEFORE a click. If the evaluation is stale
// and the server still refuses, its answer names who is open.
export default function ReportWindow({ projectId, version }) {
  const [evaluation, setEvaluation] = useState(undefined);
  const [reports, setReports] = useState([]);
  const [error, setError] = useState(null);
  const [downloading, setDownloading] = useState(null);
  const [downloadError, setDownloadError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [ev, rs] = await Promise.all([
        getEvaluation(projectId, { version }),
        listReports(projectId, { version }),
      ]);
      setEvaluation(ev);
      setReports(rs);
    } catch (err) {
      setEvaluation(null);
      setError(err);
    }
  }, [projectId, version]);

  useEffect(() => { load(); }, [load]);

  async function download(name) {
    setDownloadError(null);
    setDownloading(name);
    try {
      const { blob, filename } = await downloadReport(projectId, name, { version });
      save(blob, filename);
      setReports(await listReports(projectId, { version })); // the download set generated_at
    } catch (err) {
      setDownloadError(err.code === "review_pending"
        ? `Reports wait for every review to be confirmed. Still open: ${(err.details?.tenderers ?? []).join(", ")}.`
        : err.message);
    } finally {
      setDownloading(null);
    }
  }

  if (evaluation === undefined) return <section className="window report"><p>Loading the evaluation…</p></section>;

  if (error) {
    const message = error.code === "unconfirmed_ruleset"
      ? "No confirmed rule set yet. Confirm one in the Rules window before reporting."
      : error.message;
    return (
      <section className="window report">
        <h2>Report</h2>
        <p className="notice" role="status">{message}</p>
      </section>
    );
  }

  // Reports wait for every checked review to be confirmed (409 review_pending).
  const pending = evaluation.tenderers.filter((t) => !t.reviewed_by).map((t) => t.tenderer);

  return (
    <section className="window report">
      <h2>Report</h2>
      <p className="meta">Rule set v{evaluation.ruleset_version}</p>

      <h3>Conclusions</h3>
      <dl className="conclusions">
        <dt>Stage I</dt><dd>{evaluation.stage1_conclusion}</dd>
        <dt>Stage II</dt><dd>{evaluation.stage2_conclusion}</dd>
        <dt>Recommendation</dt><dd>{evaluation.recommendation}</dd>
      </dl>

      <h3>Tenderers</h3>
      <table>
        <caption className="sr-only">Each tenderer's stages, review and corrections</caption>
        <thead>
          <tr>
            <th scope="col">Tenderer</th><th scope="col">Stage I</th><th scope="col">Stage II</th>
            <th scope="col">Conforming</th><th scope="col">Reviewed by</th><th scope="col">Corrections</th>
          </tr>
        </thead>
        <tbody>
          {evaluation.tenderers.map((t) => (
            <tr key={t.tenderer} className={t.tenderer === evaluation.recommended ? "recommended" : ""}>
              <th scope="row">{t.tenderer}</th>
              <td>{t.stage1 ?? "—"}</td>
              <td>{t.stage2 ?? "—"}</td>
              <td>{t.conforming ? "yes" : "no"}</td>
              <td>{t.reviewed_by ?? <em>not confirmed</em>}</td>
              <td>{t.corrections}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Reports</h3>
      {pending.length > 0 && (
        <p className="notice" role="status">
          Reports wait for every review to be confirmed. Still open: {pending.join(", ")}.
        </p>
      )}
      <ul className="reports">
        {reports.map((r) => (
          <li key={r.name}>
            <button type="button" onClick={() => download(r.name)}
                    disabled={pending.length > 0 || downloading !== null}>
              {TITLES[r.name] ?? r.name}
            </button>
            <span className="meta">
              {" "}v{r.version}
              {r.approver && <> · reviews confirmed by {r.approver}</>}
              {when(r.generated_at) ? <> · last downloaded {when(r.generated_at)}</> : <> · not downloaded yet</>}
            </span>
          </li>
        ))}
      </ul>
      {downloadError && <p className="error" role="alert">{downloadError}</p>}
      {reports.length === 0 && <p className="notice">No reports for this rule-set version.</p>}
    </section>
  );
}

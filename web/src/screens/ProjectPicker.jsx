import { useEffect, useState } from "react";
import { getSettings, listProjects, REPLAY, REPLAY_LABEL } from "../api.js";
import { projectStage } from "../projectStage.js";
import NewProject from "./NewProject.jsx";

// Bottom right of a card: a green tick when the project is finished, otherwise sN, the
// step this browser last had open (s1 Rules … s5 Report).
function StageBadge({ stage }) {
  if (!stage) return null;
  const title = stage.finished
    ? "Finished: every tenderer checked and its review confirmed"
    : `In progress: last open at step ${stage.number}, ${stage.label}`;
  return (
    <span className={`project-card-stage${stage.finished ? " project-card-stage-done" : ""}`}
          title={title} aria-label={title} data-testid="project-stage">
      {stage.finished ? "✓" : `s${stage.number}`}
    </span>
  );
}

export default function ProjectPicker({ onSelect, pollMs }) {
  const [projects, setProjects] = useState(null);
  const [settings, setSettings] = useState(null);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [stages, setStages] = useState({});

  useEffect(() => {
    listProjects()
      .then(setProjects)
      .catch((err) => setError(err.message));
    // An older API without /settings is a local stack that takes uploads.
    getSettings()
      .then(setSettings)
      .catch(() => setSettings({ hosted_demo: false, uploads: true, data_classes: ["synthetic", "redacted_sample", "confidential"] }));
  }, []);

  useEffect(() => {
    if (!projects) return undefined;
    let cancelled = false;
    for (const project of projects) {
      projectStage(project.id)
        .then((stage) => !cancelled && setStages((prev) => ({ ...prev, [project.id]: stage })))
        .catch(() => {});
    }
    return () => {
      cancelled = true;
    };
  }, [projects]);

  if (error) {
    return <div className="window-status window-status-error">Failed to load projects: {error}</div>;
  }
  if (!projects) {
    return <div className="window-status">Loading projects…</div>;
  }

  return (
    <div className="project-picker">
      {REPLAY && (
        <p className="demo-banner" role="note" data-testid="replay-banner">
          <strong>{REPLAY_LABEL}.</strong> A real run of the pipeline on a synthetic tender, recorded: the rule set the
          model drafted and two people confirmed, every offer checked, the reviews, the scores and the Word reports.
          Browse every window; nothing here can be changed.
          {settings?.source_url && (
            <> To run it yourself: <a href={`${settings.source_url}#quickstart`} target="_blank" rel="noreferrer">
              {settings.source_url.replace(/^https?:\/\//, "")}</a>.</>
          )}
        </p>
      )}
      {!REPLAY && settings?.hosted_demo && (
        <p className="demo-banner" role="note" data-testid="demo-banner">
          A demo on synthetic tenders. To use your own documents, run it on a machine you control
          {settings.source_url && (
            <>
              : <a href={`${settings.source_url}#quickstart`} target="_blank" rel="noreferrer">{settings.source_url.replace(/^https?:\/\//, "")}</a>
            </>
          )}
          .
        </p>
      )}
      <div className="project-picker-head">
        <div>
          <h1>Select a project</h1>
          <p className="project-picker-subtitle">
            Each project holds the tender documents and the tenderers' offers.
          </p>
        </div>
        {!creating && !REPLAY && (
          <button type="button" className="project-picker-new" onClick={() => setCreating(true)}>
            + New project
          </button>
        )}
      </div>
      {creating && settings && (
        <NewProject settings={settings} onCreated={onSelect} onCancel={() => setCreating(false)} pollMs={pollMs} />
      )}
      <div className="project-grid">
        {projects.map((project) => (
          <button type="button" className="project-card" key={project.id} onClick={() => onSelect(project.id)}>
            <div className="project-card-id">{project.id}</div>
            <div className="project-card-name">{project.name}</div>
            <div className="project-card-meta">
              {project.data_class ?? "confidential"}
            </div>
            <StageBadge stage={stages[project.id]} />
          </button>
        ))}
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { listProjects } from "../api.js";

export default function ProjectPicker({ onSelect }) {
  const [projects, setProjects] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    listProjects()
      .then(setProjects)
      .catch((err) => setError(err.message));
  }, []);

  if (error) {
    return <div className="window-status window-status-error">Failed to load projects: {error}</div>;
  }
  if (!projects) {
    return <div className="window-status">Loading projects…</div>;
  }

  return (
    <div className="project-picker">
      <h1>Select a project</h1>
      <p className="project-picker-subtitle">
        Each project holds the tender documents and the tenderers' offers.
      </p>
      <div className="project-grid">
        {projects.map((project) => (
          <button type="button" className="project-card" key={project.id} onClick={() => onSelect(project.id)}>
            <div className="project-card-id">{project.id}</div>
            <div className="project-card-name">{project.name}</div>
            <div className="project-card-meta">
              {project.data_class ?? "confidential"}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

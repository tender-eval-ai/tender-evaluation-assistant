import { useEffect, useState } from "react";
import { listTenders } from "../api.js";

export default function ProjectPicker({ onSelect }) {
  const [projects, setProjects] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    listTenders()
      .then(setProjects)
      .catch((err) => setError(err.message));
  }, []);

  if (error) {
    return <div className="window-status window-status-error">Failed to load projects: {error}</div>;
  }
  if (!projects) {
    return <div className="window-status">Scanning local project folders…</div>;
  }

  return (
    <div className="project-picker">
      <h1>Select a project</h1>
      <p className="project-picker-subtitle">
        Each project is a local folder containing the tender documents and vendor submission(s).
      </p>
      <div className="project-grid">
        {projects.map((project) => (
          <button type="button" className="project-card" key={project.id} onClick={() => onSelect(project.id)}>
            <div className="project-card-id">{project.id}</div>
            <div className="project-card-name">{project.name}</div>
            <div className="project-card-meta">
              {project.vendors.length} vendor{project.vendors.length === 1 ? "" : "s"}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

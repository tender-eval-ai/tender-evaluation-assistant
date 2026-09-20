import StageResultsWindow from "../components/StageResultsWindow.jsx";

export default function StageIIWindow({ projectId, tenderer }) {
  return <StageResultsWindow projectId={projectId} tenderer={tenderer} stage="II" title="Stage II — Compliance" />;
}

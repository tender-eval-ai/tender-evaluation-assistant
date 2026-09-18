import StageResultsWindow from "../components/StageResultsWindow.jsx";

export default function StageIWindow({ projectId, tenderer }) {
  return <StageResultsWindow projectId={projectId} tenderer={tenderer} stage="I" title="Stage I — Completeness" />;
}

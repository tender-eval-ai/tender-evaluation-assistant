import StageResultsWindow from "../components/StageResultsWindow.jsx";

export default function Window2({ tenderId, vendorId }) {
  return <StageResultsWindow tenderId={tenderId} vendorId={vendorId} stage="I" title="Stage I — Completeness" />;
}

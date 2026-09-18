import StageResultsWindow from "../components/StageResultsWindow.jsx";

export default function Window2b({ tenderId, vendorId }) {
  return <StageResultsWindow tenderId={tenderId} vendorId={vendorId} stage="II" title="Stage II — Compliance" />;
}

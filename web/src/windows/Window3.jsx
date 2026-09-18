import { useEffect, useState } from "react";
import { getStage3PriceSummary } from "../api.js";
import PriceSummaryTable from "../components/PriceSummaryTable.jsx";

export default function Window3({ tenderId }) {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getStage3PriceSummary(tenderId)
      .then((data) => {
        setSummary(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [tenderId]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-ink-3 p-10 text-center">
        Computing the Price Summary from each vendor&rsquo;s Price Schedule…
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-mandatory p-10 text-center">
        Failed to load: {error}
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden min-h-0 bg-card">
      <PriceSummaryTable summary={summary} />
    </div>
  );
}

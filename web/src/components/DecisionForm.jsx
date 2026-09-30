import { useState } from "react";

// Deciding a check that needs review (the contract's CorrectionRequest.decision): the
// engine couldn't settle it, so a person does, with a reason, like a correction. Only
// a check that needs review is offered this; any other is settled by correcting its value.
const CHOICES = [
  ["pass", "passes"],
  ["dormant", "the Authority may ask for it later"],
  ["disqualified", "disqualifies"],
];

export default function DecisionForm({ fieldId, onSubmit, onCancel }) {
  const [decision, setDecision] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    if (!decision) return setError("Choose a decision.");
    if (!reason.trim()) return setError("A reason is required.");
    setError(null);
    setBusy(true);
    try {
      await onSubmit({ decision, reason: reason.trim() });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="correction" onSubmit={submit} aria-label={`Decide ${fieldId}`}>
      <label>
        Decision
        <select value={decision} onChange={(e) => setDecision(e.target.value)}>
          <option value="">choose…</option>
          {CHOICES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <label>
        Reason
        <input type="text" value={reason} onChange={(e) => setReason(e.target.value)}
               placeholder="what you checked, and where" />
      </label>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="actions">
        <button type="submit" disabled={busy}>{busy ? "Saving…" : "Save decision"}</button>
        <button type="button" onClick={onCancel} disabled={busy}>Cancel</button>
      </div>
    </form>
  );
}

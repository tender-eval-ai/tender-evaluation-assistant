import { useState } from "react";

// Correcting one field. `reason` is required by the contract and an empty request is
// a 400, so the form enforces both rather than letting the API refuse: a reviewer
// should be told what is missing before they submit, not after.
//
// Three kinds of correction, because the API takes three: a value, a document marked
// present or absent, and a page. Which apply depends on the field - a document field
// is present/absent, everything else is a value - so the caller says which it is.
export default function FieldCorrection({ fieldId, isDocument, currentPage, onSubmit, onCancel }) {
  const [value, setValue] = useState("");
  const [present, setPresent] = useState("");
  const [page, setPage] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const changed = isDocument ? present !== "" : value !== "";
  const pageChanged = page !== "" && Number(page) !== currentPage;

  async function submit(event) {
    event.preventDefault();
    if (!reason.trim()) return setError("A reason is required.");
    if (!changed && !pageChanged) return setError("Change a value, a document's presence, or its page.");
    setError(null);
    setBusy(true);
    try {
      const body = { reason: reason.trim() };
      if (isDocument && present !== "") body.present = present === "present";
      if (!isDocument && value !== "") body.value = value;
      if (pageChanged) body.page = Number(page);
      await onSubmit(body);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="correction" onSubmit={submit} aria-label={`Correct ${fieldId}`}>
      {isDocument ? (
        <label>
          Document
          <select value={present} onChange={(e) => setPresent(e.target.value)}>
            <option value="">unchanged</option>
            <option value="present">present</option>
            <option value="absent">absent</option>
          </select>
        </label>
      ) : (
        <label>
          Value
          <input type="text" value={value} onChange={(e) => setValue(e.target.value)}
                 placeholder="the value as printed" />
        </label>
      )}

      <label>
        Page
        <input type="number" min="1" value={page} onChange={(e) => setPage(e.target.value)}
               placeholder={currentPage ? String(currentPage) : "page"} />
      </label>

      <label>
        Reason
        <input type="text" value={reason} onChange={(e) => setReason(e.target.value)}
               placeholder="why this is being corrected" />
      </label>

      {error && <p className="error" role="alert">{error}</p>}

      <div className="actions">
        <button type="submit" disabled={busy}>{busy ? "Saving…" : "Save correction"}</button>
        <button type="button" onClick={onCancel} disabled={busy}>Cancel</button>
      </div>
    </form>
  );
}

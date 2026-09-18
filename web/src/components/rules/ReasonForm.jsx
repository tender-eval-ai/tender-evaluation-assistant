import { useState } from "react";
import { locText } from "./values.js";

// Shared look for the Rules window's inputs.
export const inputCls =
  "w-full px-2 py-1 text-xs border border-border rounded bg-card text-ink " +
  "focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-1";
export const monoInputCls = `${inputCls} font-mono`;
export const buttonCls =
  "px-2.5 py-1 text-xs font-mono font-medium rounded border border-accent bg-accent-wash text-accent-strong " +
  "hover:bg-accent hover:text-white transition-colors cursor-pointer " +
  "disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-accent-wash disabled:hover:text-accent-strong";
export const quietButtonCls =
  "px-2 py-0.5 text-xs font-mono rounded border border-border-soft text-ink-3 hover:border-border " +
  "hover:text-ink transition-colors cursor-pointer";
export const dangerButtonCls =
  "px-2.5 py-1 text-xs font-mono font-medium rounded border border-mandatory/50 bg-mandatory-wash text-mandatory " +
  "hover:bg-mandatory hover:text-white transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed";

// An ApiError as a person reads it: the message, then each validation error
// the API listed in details.errors.
export function ApiErrorText({ error }) {
  if (!error) return null;
  const errors = Array.isArray(error.details?.errors) ? error.details.errors : [];
  return (
    <div role="alert" className="px-2.5 py-2 rounded border border-mandatory/40 bg-mandatory-wash text-xs text-mandatory">
      <p className="font-medium">{error.message}</p>
      {errors.length > 0 && (
        <ul className="list-disc pl-4 mt-1 space-y-0.5">
          {errors.map((e, i) => (
            <li key={i}>
              {locText(e.loc) && <span className="font-mono">{locText(e.loc)}: </span>}
              {String(e.msg ?? "").replace(/^Value error, /, "")}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Every human change to a rule set carries a reason (Edit.reason, min length
// 1). The form keeps Save disabled until one is written, and shows what the
// API answered when the change is refused.
export default function ReasonForm({ title, submitLabel = "Save", danger = false, canSubmit = true, onSubmit, onCancel, children }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const missing = !reason.trim();

  function submit(e) {
    e.preventDefault();
    if (missing || !canSubmit) return;
    setBusy(true);
    setError(null);
    Promise.resolve()
      .then(() => onSubmit(reason.trim()))
      .catch((err) => setError(err))
      .finally(() => setBusy(false));
  }

  return (
    <form onSubmit={submit} aria-label={title} className="flex flex-col gap-2 p-2.5 border border-accent/30 rounded bg-accent-wash/40">
      {title && <p className="font-mono text-xs uppercase tracking-wider text-accent-strong">{title}</p>}
      {children}
      <label className="flex flex-col gap-1 text-xs text-ink-3">
        Reason (required)
        <textarea
          rows={2}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className={inputCls}
          placeholder="Why this change? It is recorded with your name and the time."
        />
      </label>
      {missing && <p className="text-xs text-ink-4">A reason is required before the change can be saved.</p>}
      <ApiErrorText error={error} />
      <div className="flex gap-2">
        <button type="submit" disabled={missing || !canSubmit || busy} className={danger ? dangerButtonCls : buttonCls}>
          {busy ? "saving…" : submitLabel}
        </button>
        <button type="button" onClick={onCancel} className={quietButtonCls}>
          Cancel
        </button>
      </div>
    </form>
  );
}

import { useEffect, useState } from "react";
import { getRuleset, getRulesetDiff } from "../../api.js";
import { ApiErrorText, inputCls } from "./ReasonForm.jsx";
import { showValue, when } from "./values.js";

// The value of one Diff field in an item: "slots.<name>", "rules.<id>" or an
// item field.
function fieldValue(item, field) {
  if (!item) return undefined;
  if (field.startsWith("slots.")) return item.slots?.[field.slice(6)];
  if (field.startsWith("rules.")) return item.rules?.find((r) => r.id === field.slice(6));
  return item[field];
}

function Value({ value }) {
  if (value === undefined) return <span className="text-ink-4">absent</span>;
  if (value !== null && typeof value === "object") {
    return <pre className="text-xs font-mono whitespace-pre-wrap break-all text-ink-2 m-0">{JSON.stringify(value, null, 1)}</pre>;
  }
  return <span className="font-mono text-xs text-ink-2">{showValue(value)}</span>;
}

// GET .../ruleset/diff?from=&to= between two versions, with each changed
// field's value before and after (from GET .../ruleset?version=).
export default function DiffPanel({ projectId, versions, initialFrom, initialTo }) {
  const [from, setFrom] = useState(initialFrom);
  const [to, setTo] = useState(initialTo);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    if (from == null || to == null) return undefined;
    setError(null);
    setResult(null);
    Promise.all([getRulesetDiff(projectId, from, to), getRuleset(projectId, { version: from }), getRuleset(projectId, { version: to })])
      .then(([diff, a, b]) => !cancelled && setResult({ diff, a, b }))
      .catch((err) => !cancelled && setError(err));
    return () => {
      cancelled = true;
    };
  }, [projectId, from, to]);

  const pick = (label, value, onChange) => (
    <label className="flex items-center gap-1.5 text-xs text-ink-3">
      {label}
      <select aria-label={`${label} version`} value={value ?? ""} onChange={(e) => onChange(Number(e.target.value))} className={`${inputCls} w-auto`}>
        {versions.map((v) => (
          <option key={v.version} value={v.version}>
            v{v.version} · {v.status}
          </option>
        ))}
      </select>
    </label>
  );

  const byLetter = (rs) => new Map((rs?.items ?? []).map((i) => [i.letter, i]));
  const before = byLetter(result?.a);
  const after = byLetter(result?.b);
  const d = result?.diff;
  const empty = d && !d.added.length && !d.removed.length && !d.changed.length;

  return (
    <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3" data-testid="diff">
      <div className="flex items-center gap-3 flex-wrap">
        {pick("From", from, setFrom)}
        {pick("To", to, setTo)}
      </div>
      <ApiErrorText error={error} />
      {!d && !error && <p className="text-xs text-ink-3">Loading the diff…</p>}
      {empty && <p className="text-xs text-ink-3">No differences between v{d.from} and v{d.to}.</p>}

      {d?.added.length > 0 && (
        <section>
          <p className="font-mono text-xs uppercase tracking-wider text-ok mb-1">Added</p>
          {d.added.map((l) => (
            <p key={l} className="text-xs text-ink-2" data-testid={`diff-added-${l}`}>
              <span className="font-mono font-semibold">({l})</span> {after.get(l)?.title}
            </p>
          ))}
        </section>
      )}
      {d?.removed.length > 0 && (
        <section>
          <p className="font-mono text-xs uppercase tracking-wider text-mandatory mb-1">Removed</p>
          {d.removed.map((l) => (
            <p key={l} className="text-xs text-ink-2" data-testid={`diff-removed-${l}`}>
              <span className="font-mono font-semibold">({l})</span> {before.get(l)?.title}
            </p>
          ))}
        </section>
      )}
      {d?.changed.length > 0 && (
        <section className="flex flex-col gap-2">
          <p className="font-mono text-xs uppercase tracking-wider text-rectifiable">Changed</p>
          {d.changed.map((c) => (
            <div key={c.letter} className="p-2.5 border border-border-soft rounded bg-faint" data-testid={`diff-changed-${c.letter}`}>
              <p className="text-xs text-ink-2">
                <span className="font-mono font-semibold">({c.letter})</span> {after.get(c.letter)?.title}
              </p>
              {c.edit ? (
                <p className="text-xs text-ink-3 mt-0.5">
                  by <span className="font-medium text-ink-2">{c.edit.by}</span> · {when(c.edit.at)} ·{" "}
                  <span className="italic">“{c.edit.reason}”</span>
                </p>
              ) : (
                <p className="text-xs text-ink-4 mt-0.5">changed by the rule builder (no human edit)</p>
              )}
              <table className="w-full mt-2 text-xs border-collapse">
                <thead>
                  <tr className="text-left text-ink-4 font-mono">
                    <th className="py-1 pr-2 font-normal">field</th>
                    <th className="py-1 pr-2 font-normal">v{d.from}</th>
                    <th className="py-1 font-normal">v{d.to}</th>
                  </tr>
                </thead>
                <tbody>
                  {c.fields.map((f) => (
                    <tr key={f} className="align-top border-t border-border-soft">
                      <td className="py-1 pr-2 font-mono text-ink-3">{f}</td>
                      <td className="py-1 pr-2">
                        <Value value={fieldValue(before.get(c.letter), f)} />
                      </td>
                      <td className="py-1">
                        <Value value={fieldValue(after.get(c.letter), f)} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

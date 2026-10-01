import { useState } from "react";
import ReasonForm, { quietButtonCls } from "./ReasonForm.jsx";

// Uncovered clauses and "shall/must" sentences (GET .../ruleset/gaps). A gap
// blocks confirmation until a person says why no rule covers it. The reason is
// saved with the whole draft (PUT .../ruleset/draft), so one reason can go to
// every open gap in one save: a synthetic tender left 72, most of them the
// Authority's own obligations (2026-09-30).
export default function GapsPanel({ gaps, editable, onSaveReason, onSaveReasons }) {
  const [editing, setEditing] = useState(null);

  if (!gaps) return <p className="p-4 text-xs text-ink-3">Loading the gaps…</p>;
  if (gaps.length === 0) return <p className="p-4 text-xs text-ink-3">No gaps: every clause the schedule points to has a rule.</p>;

  const open = gaps.filter((g) => !g.reason);

  return (
    <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-2" data-testid="gaps">
      {editable && onSaveReasons && open.length > 1 && (
        <div className="p-2.5 border border-border rounded bg-bg" data-testid="gaps-all">
          {editing === "*" ? (
            <ReasonForm
              title={`Why no rule covers any of the ${open.length} open gaps`}
              submitLabel={`Save the reason for all ${open.length}`}
              onCancel={() => setEditing(null)}
              onSubmit={(reason) => onSaveReasons(open.map((g) => g.node_id), reason).then(() => setEditing(null))}
            />
          ) : (
            <button type="button" className={quietButtonCls} onClick={() => setEditing("*")}>
              give one reason to all {open.length} open gaps
            </button>
          )}
        </div>
      )}
      {gaps.map((g) => (
        <div
          key={g.node_id}
          data-testid={`gap-${g.node_id}`}
          className={`p-2.5 border rounded ${g.reason ? "border-border-soft bg-faint" : "border-mandatory/40 bg-mandatory-wash/40"}`}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono text-xs text-ink-2">{g.node_id}</span>
            {editable && editing !== g.node_id && (
              <button type="button" className={quietButtonCls} onClick={() => setEditing(g.node_id)} aria-label={`give a reason for gap ${g.node_id}`}>
                {g.reason ? "change reason" : "give a reason"}
              </button>
            )}
          </div>
          <p className="text-sm text-ink mt-1">{g.text}</p>
          <p className={`text-xs mt-1 ${g.reason ? "text-ink-3" : "text-mandatory"}`}>
            {g.reason ? <>No rule because: <span className="italic">{g.reason}</span></> : "No reason given yet: blocks confirmation"}
          </p>
          {editing === g.node_id && (
            <div className="mt-2">
              <ReasonForm
                title={`Why no rule covers ${g.node_id}`}
                submitLabel="Save the reason"
                onCancel={() => setEditing(null)}
                onSubmit={(reason) => onSaveReason(g.node_id, reason).then(() => setEditing(null))}
              />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

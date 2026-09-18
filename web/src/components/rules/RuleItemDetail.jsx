import { useState } from "react";
import Badge from "../Badge.jsx";
import CollapsibleSection from "../CollapsibleSection.jsx";
import ReasonForm, { dangerButtonCls, inputCls, monoInputCls, quietButtonCls } from "./ReasonForm.jsx";
import { parseValue, showValue, when } from "./values.js";

const TIER = {
  A: { label: "Mandatory", cls: "text-mandatory border-mandatory/40" },
  B: { label: "Rectifiable", cls: "text-rectifiable border-rectifiable/40" },
  C: { label: "Discretionary", cls: "text-discretionary border-border" },
};

function CitationButton({ citation, onViewReference, label }) {
  return (
    <button
      type="button"
      onClick={() => onViewReference(citation, label)}
      className="flex items-center justify-between gap-2 px-2.5 py-2 border border-border-soft rounded
        bg-faint text-left w-full transition-colors cursor-pointer hover:border-border
        focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
    >
      <span className="text-xs text-ink-2 min-w-0 line-clamp-2">{citation.quote}</span>
      <span className="font-mono text-xs text-ink-4 shrink-0">p.{citation.page} →</span>
    </button>
  );
}

function EditRecord({ edit, prefix = "Edited" }) {
  if (!edit) return null;
  return (
    <p className="text-xs text-ink-3">
      {prefix} by <span className="font-medium text-ink-2">{edit.by}</span> · {when(edit.at)} ·{" "}
      <span className="italic">“{edit.reason}”</span>
    </p>
  );
}

function EditButton({ label, onClick }) {
  return (
    <button type="button" onClick={onClick} className={quietButtonCls} aria-label={label}>
      edit
    </button>
  );
}

// A filled slot. After a person corrects it the model's value stays beside
// the correction (`model_value`), with who changed it, when and why.
function Slot({ name, slot, editing, onEdit, onCancel, onSave, onViewReference, editable }) {
  const [text, setText] = useState(slot.value == null ? "" : showValue(slot.value));
  const manual = slot.origin === "manual";
  return (
    <div className="p-2.5 border border-border-soft rounded bg-faint flex flex-col gap-1" data-testid={`slot-${name}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs text-ink-2">{name}</span>
        <span className="flex items-center gap-2">
          <span className="font-mono text-xs text-ink-4">
            {slot.origin}
            {slot.verified ? " · verified" : " · unverified"}
          </span>
          {editable && !editing && <EditButton label={`edit slot ${name}`} onClick={onEdit} />}
        </span>
      </div>
      <p className="text-sm text-ink">
        {slot.value == null ? <span className="text-mandatory">empty — needs a value</span> : showValue(slot.value)}
      </p>
      {manual && (
        <p className="text-xs text-ink-3" data-testid={`model-value-${name}`}>
          Model’s value: <span className="font-mono">{showValue(slot.model_value)}</span>
        </p>
      )}
      <EditRecord edit={slot.edit} prefix="Corrected" />
      {slot.citation && (
        <CitationButton citation={slot.citation} onViewReference={onViewReference} label={`slot ${name}`} />
      )}
      {editing && (
        <ReasonForm title={`Correct slot ${name}`} onCancel={onCancel} onSubmit={(reason) => onSave({ slot: { name, value: parseValue(text) } }, reason)}>
          <label className="flex flex-col gap-1 text-xs text-ink-3">
            New value (a number, true/false, JSON, or text)
            <input value={text} onChange={(e) => setText(e.target.value)} className={monoInputCls} />
          </label>
        </ReasonForm>
      )}
    </div>
  );
}

// A rule is edited as JSON: TemplateRule has a dozen fields, and the API
// validates the whole of it (a gate names a consequence or its own outcomes).
function RuleJsonForm({ title, initial, onCancel, onSave }) {
  const [text, setText] = useState(JSON.stringify(initial, null, 2));
  let parsed = null;
  let parseError = null;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    parseError = err.message;
  }
  return (
    <ReasonForm title={title} canSubmit={!parseError} onCancel={onCancel} onSubmit={(reason) => onSave({ rule: parsed }, reason)}>
      <textarea
        aria-label="Rule JSON"
        rows={Math.min(18, text.split("\n").length + 1)}
        value={text}
        onChange={(e) => setText(e.target.value)}
        className={monoInputCls}
        spellCheck={false}
      />
      {parseError && <p className="text-xs text-mandatory">Not valid JSON: {parseError}</p>}
    </ReasonForm>
  );
}

function TextForm({ title, label, initial = "", onCancel, onSubmit }) {
  const [text, setText] = useState(initial);
  return (
    <ReasonForm title={title} onCancel={onCancel} onSubmit={(reason) => onSubmit(text, reason)}>
      <label className="flex flex-col gap-1 text-xs text-ink-3">
        {label}
        <input value={text} onChange={(e) => setText(e.target.value)} className={inputCls} />
      </label>
    </ReasonForm>
  );
}

const NEW_RULE = {
  id: "item.new_rule",
  check: "filled",
  field: "item.field",
  params: {},
  outcomes: { blank: { status: "needs_review" }, filled: { status: "pass" } },
  stage: "I",
};

// One RuleSetItem, editable: the schedule row it comes from, its clauses,
// template, slots, rules and notes. Every change goes through PATCH
// .../items/{letter} with a reason; deleting through DELETE with a reason.
export default function RuleItemDetail({ item, editable, onViewReference, onPatch, onDelete }) {
  const [editing, setEditing] = useState(null);

  if (!item) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-center text-xs text-ink-4">
        Select a requirement to see its full text, source page and rules.
      </div>
    );
  }

  const tier = TIER[item.part] ?? TIER.C;
  const close = () => setEditing(null);
  const save = (patch, reason) => onPatch(item.letter, { ...patch, reason }).then(close);
  const slots = Object.entries(item.slots ?? {});

  return (
    <div className="flex-1 overflow-y-auto p-4" data-testid="rule-item-detail">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono text-sm font-bold text-accent-strong">({item.letter})</span>
          <span className="font-mono text-xs text-ink-4">Part {item.part}</span>
          <Badge kind={item.status} />
        </div>
        <span className={`px-2 py-0.5 text-xs border rounded font-medium shrink-0 ${tier.cls}`}>{tier.label}</span>
      </div>

      <p className="text-sm leading-6 text-ink font-medium mb-1">{item.title}</p>
      <div className="mb-3">
        <EditRecord edit={item.edit} prefix="Last edited" />
      </div>

      <CollapsibleSection title="Schedule row" defaultOpen>
        <p className="text-sm leading-6 text-ink-2 border-l-2 border-border pl-3 mb-2">{item.citation.quote}</p>
        <CitationButton citation={item.citation} onViewReference={onViewReference} label={`(${item.letter}) — schedule row`} />
      </CollapsibleSection>

      {item.clauses?.length > 0 && (
        <CollapsibleSection title="Referenced clauses">
          <div className="flex flex-col gap-1">
            {item.clauses.map((c) => (
              <CitationButton key={`${c.file}-${c.page}-${c.node_id}`} citation={c} onViewReference={onViewReference} label={c.node_id ?? c.file} />
            ))}
          </div>
        </CollapsibleSection>
      )}

      <CollapsibleSection title="Template" defaultOpen>
        <div className="flex items-center justify-between gap-2 mb-1">
          <span className="font-mono text-xs text-ink-2">{item.template ?? "none — the rules carry their own outcomes"}</span>
          {editable && editing !== "template" && <EditButton label="edit template" onClick={() => setEditing("template")} />}
        </div>
        {editing === "template" && (
          <TextForm
            title="Change the template"
            label="Template id (empty for none)"
            initial={item.template ?? ""}
            onCancel={close}
            onSubmit={(text, reason) => save({ template: text.trim() || null }, reason)}
          />
        )}
      </CollapsibleSection>

      {slots.length > 0 && (
        <CollapsibleSection title={`Slots · ${slots.length}`} defaultOpen>
          <div className="flex flex-col gap-1.5">
            {slots.map(([name, slot]) => (
              <Slot
                key={`${name}-${showValue(slot.value)}`}
                name={name}
                slot={slot}
                editable={editable}
                editing={editing === `slot:${name}`}
                onEdit={() => setEditing(`slot:${name}`)}
                onCancel={close}
                onSave={save}
                onViewReference={onViewReference}
              />
            ))}
          </div>
        </CollapsibleSection>
      )}

      <CollapsibleSection title={`Rules · ${item.rules.length}`} defaultOpen>
        <div className="flex flex-col gap-1.5">
          {item.rules.map((r) => (
            <div key={r.id} className="p-2.5 border border-border-soft rounded bg-faint" data-testid={`rule-${r.id}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-ink-2">{r.id}</span>
                <span className="flex items-center gap-2 shrink-0">
                  <span className="font-mono text-xs text-ink-4">
                    {r.check} · Stage {r.stage}
                    {r.consequence ? ` · ${r.consequence}` : ""}
                  </span>
                  {editable && editing !== `rule:${r.id}` && <EditButton label={`edit rule ${r.id}`} onClick={() => setEditing(`rule:${r.id}`)} />}
                </span>
              </div>
              <p className="text-xs text-ink-3 mt-1">
                {r.field}
                {Object.keys(r.params ?? {}).length > 0 && <span className="font-mono text-ink-4"> · {JSON.stringify(r.params)}</span>}
                {r.depends_on?.length > 0 && <span className="text-ink-4"> · after {r.depends_on.join(", ")}</span>}
              </p>
              {r.outcomes && (
                <p className="text-xs text-ink-4 mt-1 font-mono">
                  {Object.entries(r.outcomes)
                    .map(([k, o]) => `${k} → ${o.status}`)
                    .join(" · ")}
                </p>
              )}
              {r.note && <p className="text-xs text-ink-4 mt-1">{r.note}</p>}
              {editing === `rule:${r.id}` && (
                <div className="mt-2">
                  <RuleJsonForm title={`Edit rule ${r.id}`} initial={r} onCancel={close} onSave={save} />
                </div>
              )}
            </div>
          ))}
          {editable &&
            (editing === "rule:new" ? (
              <RuleJsonForm title="Add a rule" initial={NEW_RULE} onCancel={close} onSave={save} />
            ) : (
              <button type="button" onClick={() => setEditing("rule:new")} className={`${quietButtonCls} self-start`}>
                + add a rule
              </button>
            ))}
        </div>
      </CollapsibleSection>

      <CollapsibleSection title={`Notes · ${item.notes?.length ?? 0}`} defaultOpen={item.notes?.length > 0}>
        <ul className="list-disc list-outside pl-4 space-y-1 mb-2">
          {(item.notes ?? []).map((n, i) => (
            <li key={i} className="text-xs text-ink-2">
              <span className="font-mono text-ink-4">{n.kind} </span>
              {n.text}
            </li>
          ))}
        </ul>
        {editable &&
          (editing === "note" ? (
            <TextForm title="Add a note" label="Note" onCancel={close} onSubmit={(text, reason) => save({ note: text.trim() }, reason)} />
          ) : (
            <button type="button" onClick={() => setEditing("note")} className={quietButtonCls}>
              + add a note
            </button>
          ))}
      </CollapsibleSection>

      {editable && (
        <div className="mt-4 pt-3 border-t border-border-soft">
          {editing === "delete" ? (
            <ReasonForm title={`Delete item (${item.letter})`} submitLabel="Delete the item" danger onCancel={close} onSubmit={(reason) => onDelete(item.letter, reason)}>
              <p className="text-xs text-ink-3">The item leaves the draft. The diff and the audit log keep it, with your reason.</p>
            </ReasonForm>
          ) : (
            <button type="button" onClick={() => setEditing("delete")} className={dangerButtonCls}>
              Delete item ({item.letter})
            </button>
          )}
        </div>
      )}
    </div>
  );
}

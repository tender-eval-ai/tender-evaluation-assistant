import { useState } from "react";
import Badge from "./Badge.jsx";
import CollapsibleSection from "./CollapsibleSection.jsx";
import DecisionForm from "./DecisionForm.jsx";
import FieldCorrection from "./FieldCorrection.jsx";
import { fieldName, stageRollup, uniqueCitations } from "../verdicts.js";

function formatValue(value) {
  if (value === null || value === undefined || value === "") return "— blank —";
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

const fieldLabel = (fieldId) => fieldName(fieldId).replace(/_/g, " ");

// A redacted field's `value` is null too (there's nothing legible to
// transcribe behind the black bar) - formatValue alone would render that as
// "— blank —", which reads as "nothing was ever filled in". Redacted means
// the opposite: something IS there, it just can't be read from this copy.
function fieldValueDisplay(check, value) {
  return check.redacted || value?.redacted ? "content present, redacted in this copy" : formatValue(value?.value);
}

function FieldMicroLabel({ children }) {
  return <p className="font-mono text-[10px] font-semibold text-ink-3 uppercase tracking-wider mb-1">{children}</p>;
}

function FieldRow({ check, value, onViewCitation, letter, onCorrect }) {
  const page = value?.page;
  const [correcting, setCorrecting] = useState(false);
  const [deciding, setDeciding] = useState(false);
  // The field's key inside BidResult.fields. `check.field` carries it when the rule
  // and the field are named differently; otherwise it is the last segment of the id.
  const fieldKey = check.field ?? check.field_id.split(".").pop();
  const isDocument = fieldKey === "document";
  return (
    <div className="p-2.5 border border-border-soft rounded bg-faint" data-testid={`check-${check.field_id}`}>
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="text-xs font-medium text-ink-2">{fieldLabel(check.field_id)}</span>
        <Badge kind={check.status} />
      </div>
      <div className="mb-2 pl-2 border-l-2 border-border-soft">
        <FieldMicroLabel>Shown</FieldMicroLabel>
        <p className={`font-mono text-xs ${check.redacted ? "text-rectifiable" : "text-ink-3"}`}>
          {fieldValueDisplay(check, value)}
          {value?.confidence != null && (
            <span className="text-ink-4"> · confidence {Math.round(value.confidence * 100)}%</span>
          )}
        </p>
      </div>
      {check.note && (
        <div className="mb-2 pl-2 border-l-2 border-border-soft">
          <FieldMicroLabel>Why flagged</FieldMicroLabel>
          <p className="text-xs leading-5 text-ink-2">{check.note}</p>
        </div>
      )}
      {check.status === "dormant" && check.follow_up && (
        <div className="mt-1.5 p-2 bg-bg rounded border border-border text-xs text-ink-3 leading-5">
          <p>
            <span className="font-mono text-ink-4">TRIGGER </span>
            {check.follow_up.trigger}
          </p>
          <p>
            <span className="font-mono text-ink-4">DEADLINE </span>
            {check.follow_up.computed_deadline ?? check.follow_up.deadline}
          </p>
          <p>
            <span className="font-mono text-ink-4">IF MISSED </span>
            {check.follow_up.if_deadline_missed}
          </p>
        </div>
      )}
      {value?.correction && (
        <div className="mb-2 pl-2 border-l-2 border-accent" data-testid={`corrected-${check.field_id}`}>
          <FieldMicroLabel>Corrected</FieldMicroLabel>
          <p className="text-xs leading-5 text-ink-2">
            {value.model_value !== undefined && value.model_value !== value.value && (
              <>was <span className="font-mono">{formatValue(value.model_value)}</span> · </>
            )}
            {value.correction.by} · {value.correction.reason}
          </p>
        </div>
      )}
      {check.decision && (
        <div className="mb-2 pl-2 border-l-2 border-accent" data-testid={`decided-${check.field_id}`}>
          <FieldMicroLabel>Decided</FieldMicroLabel>
          <p className="text-xs leading-5 text-ink-2">
            {check.decision.status} · {check.decision.by} · {check.decision.reason}
          </p>
        </div>
      )}
      {page && (
        <button
          type="button"
          onClick={() => onViewCitation(page)}
          className="font-mono text-xs text-accent hover:underline cursor-pointer"
        >
          read on {page.file}, p.{page.page} →
        </button>
      )}
      {onCorrect && !correcting && !deciding && (
        <button type="button" onClick={() => setCorrecting(true)}
                className="font-mono text-xs text-accent hover:underline cursor-pointer">
          correct this field
        </button>
      )}
      {onCorrect && check.status === "needs_review" && !correcting && !deciding && (
        <button type="button" onClick={() => setDeciding(true)}
                className="font-mono text-xs text-accent hover:underline cursor-pointer ml-3">
          decide this check
        </button>
      )}
      {onCorrect && deciding && (
        <DecisionForm
          fieldId={check.field_id}
          onCancel={() => setDeciding(false)}
          onSubmit={async (body) => {
            await onCorrect(letter, fieldKey, body);
            setDeciding(false);
          }}
        />
      )}
      {onCorrect && correcting && (
        <FieldCorrection
          fieldId={check.field_id}
          isDocument={isDocument}
          currentPage={page?.page}
          onCancel={() => setCorrecting(false)}
          onSubmit={async (body) => {
            await onCorrect(letter, fieldKey, body);
            setCorrecting(false);
          }}
        />
      )}
    </div>
  );
}

function FieldGroup({ title, checks, values, onViewCitation, letter, onCorrect }) {
  const [expanded, setExpanded] = useState(false);
  if (checks.length === 0) return null;
  const active = checks.filter((c) => c.status !== "dormant");
  const dormant = checks.filter((c) => c.status === "dormant");
  const row = (c) => (
    <FieldRow key={c.field_id} check={c} value={values?.[fieldName(c.field_id)]}
              onViewCitation={onViewCitation} letter={letter} onCorrect={onCorrect} />
  );
  return (
    <div className="mb-3">
      <p className="font-mono text-xs text-ink-4 uppercase tracking-wider mb-1.5">
        {title} · {checks.length} field{checks.length === 1 ? "" : "s"}
      </p>
      <div className="flex flex-col gap-1.5">{active.map(row)}</div>
      {dormant.length > 0 && (
        <div className="mt-1.5">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="font-mono text-xs text-ink-4 hover:text-ink-2 cursor-pointer"
          >
            {expanded ? "▾" : "▸"} {dormant.length} not yet required
          </button>
          {expanded && <div className="flex flex-col gap-1.5 mt-1.5">{dormant.map(row)}</div>}
        </div>
      )}
    </div>
  );
}

// The per-item breakdown on the Stage I and Stage II pages, one Verdict of a
// BidResult: EVIDENCE (the offer pages the checker read), RULES (every
// checked field with the value read and its status), REFERENCES (the rule
// set's schedule row and clauses in the tender).
export default function VendorItemDetail({ item, verdict, values, stageFilter, onViewCitation, onViewTender, onCorrect }) {
  const checks = verdict?.checks ?? [];
  const rollup = verdict ? stageRollup(checks, stageFilter ?? "I") : null;
  const stageChecks = checks.filter((c) => (stageFilter === "II" ? c.stage === "II" : c.stage !== "II"));
  const evidence = uniqueCitations(verdict?.evidence);

  return (
    <>
      <p className="text-sm leading-6 text-ink font-medium mb-3">{item.title}</p>

      <CollapsibleSection title="Evidence" defaultOpen>
        {!verdict ? (
          <p className="text-xs text-ink-4">Not checked yet — click "Run check" above.</p>
        ) : evidence.length > 0 ? (
          <div className="flex flex-col gap-1.5">
            {evidence.map((c) => (
              <button
                key={`${c.doc_id}-${c.page}`}
                type="button"
                onClick={() => onViewCitation(c)}
                className="flex items-center justify-between gap-2 px-2.5 py-2 border border-border-soft rounded
                  bg-faint text-left w-full transition-colors cursor-pointer hover:border-border
                  focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
              >
                <span className="text-xs text-ink-2 truncate">{c.file}</span>
                <span className="font-mono text-xs text-accent-strong shrink-0">p.{c.page} →</span>
              </button>
            ))}
          </div>
        ) : (
          <p className="text-xs text-ink-4">No page of the offer was cited for this item.</p>
        )}
      </CollapsibleSection>

      <CollapsibleSection title="Rules" defaultOpen>
        {!verdict ? (
          <p className="text-xs text-ink-4">Not checked yet — click "Run check" above.</p>
        ) : (
          <div>
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <Badge kind={rollup.status} />
              <span className="font-mono text-xs text-ink-4">
                {rollup.counts.pass ?? 0} pass · {rollup.counts.needs_review ?? 0} needs review ·{" "}
                {rollup.counts.disqualified ?? 0} disqualifying · {rollup.counts.dormant ?? 0} dormant
              </span>
            </div>
            {verdict.reason && <p className="text-xs leading-5 text-ink-2 mb-3">{verdict.reason}</p>}
            <FieldGroup
              title={stageFilter === "II" ? "Stage II — Essential Requirements" : "Stage I — Completeness"}
              checks={stageChecks}
              values={values}
              onViewCitation={onViewCitation}
              letter={item?.letter}
              onCorrect={onCorrect}
            />
            {verdict.rule_ids.length > 0 && (
              <p className="font-mono text-[10px] text-ink-4 break-all">rules: {verdict.rule_ids.join(", ")}</p>
            )}
          </div>
        )}
      </CollapsibleSection>

      {item.citation && (
        <CollapsibleSection title="References">
          <div className="flex flex-col gap-1">
            {[item.citation, ...(item.clauses ?? [])].map((ref) => (
              <button
                type="button"
                key={`${ref.file}-${ref.page}-${ref.node_id}`}
                onClick={() => onViewTender(ref)}
                className="flex items-center justify-between gap-2 px-2.5 py-2 border border-border-soft rounded
                  bg-faint text-left w-full transition-colors cursor-pointer hover:border-border
                  focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
              >
                <span className="text-xs text-ink-2 min-w-0 line-clamp-2">{ref.quote}</span>
                <span className="font-mono text-xs text-ink-4 shrink-0">p.{ref.page} →</span>
              </button>
            ))}
          </div>
        </CollapsibleSection>
      )}
    </>
  );
}

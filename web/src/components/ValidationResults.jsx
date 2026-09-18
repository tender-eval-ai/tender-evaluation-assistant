import { useState } from "react";
import Badge from "./Badge.jsx";
import CollapsibleSection from "./CollapsibleSection.jsx";

function formatValue(value) {
  if (value === null || value === undefined || value === "") return "— blank —";
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

const DECISION_LABEL = { confirmed: "Confirmed", rejected: "Rejected", flagged: "Flagged" };
// Tailwind utilities actually defined in index.css's @theme block
// (text-ok/text-mandatory/text-rectifiable -> --good/--crit/--warn) - not
// text-good/text-crit/text-warn, which don't exist as utilities.
const DECISION_TONE = { confirmed: "ok", rejected: "mandatory", flagged: "rectifiable" };

function formatDecidedAt(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

// Reviewer decision on this one field - independent of the checker's own
// computed `status` (Badge above), but only rendered by FieldRow when that
// status is "needs_review": pass/disqualified/dormant are already a
// settled machine verdict with nothing for a human to act on, and showing
// the same three buttons under every row (tried first) buried the fields
// that actually need attention among ones that don't.
function FieldDecisionControls({ field, letter, review, onDecision }) {
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteDraft, setNoteDraft] = useState(review?.note ?? "");
  const [saving, setSaving] = useState(false);

  function submit(decision, note) {
    setSaving(true);
    Promise.resolve(onDecision(letter, field.field_id, decision, note, field.status)).finally(() => {
      setSaving(false);
      setNoteOpen(false);
    });
  }

  if (review && review.decision !== "pending" && !noteOpen) {
    return (
      <div className="mt-1.5 pt-1.5 border-t border-border-soft flex items-center justify-between gap-2 flex-wrap">
        <span className="text-xs text-ink-3">
          <span className={`font-medium text-${DECISION_TONE[review.decision]}`}>
            {DECISION_LABEL[review.decision] ?? review.decision}
          </span>{" "}
          by {review.reviewer} · {formatDecidedAt(review.decided_at)}
          {review.note && <span className="block text-ink-2 mt-0.5">"{review.note}"</span>}
        </span>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={() => {
              setNoteDraft(review.note ?? "");
              setNoteOpen(true);
            }}
            disabled={saving}
            className="font-mono text-xs text-ink-4 hover:text-ink-2 cursor-pointer"
          >
            change
          </button>
          <button
            type="button"
            onClick={() => submit("pending", null)}
            disabled={saving}
            className="font-mono text-xs text-ink-4 hover:text-ink-2 cursor-pointer"
          >
            clear
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-1.5 pt-1.5 border-t border-border-soft">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => submit("confirmed", null)}
          disabled={saving}
          className="font-mono text-xs text-ok hover:underline cursor-pointer"
        >
          ✓ Confirm
        </button>
        <button
          type="button"
          onClick={() => submit("rejected", null)}
          disabled={saving}
          className="font-mono text-xs text-mandatory hover:underline cursor-pointer"
        >
          ✕ Reject
        </button>
        <button
          type="button"
          onClick={() => setNoteOpen((v) => !v)}
          disabled={saving}
          className="font-mono text-xs text-rectifiable hover:underline cursor-pointer"
        >
          {"\u{1F4DD}"} Note
        </button>
      </div>
      {noteOpen && (
        <div className="mt-1.5 flex items-start gap-1.5">
          <textarea
            value={noteDraft}
            onChange={(e) => setNoteDraft(e.target.value)}
            placeholder="Not sure — leave a note for the next reviewer"
            rows={2}
            className="flex-1 text-xs p-1.5 border border-border rounded bg-card resize-none
              focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-1"
          />
          <button
            type="button"
            onClick={() => submit("flagged", noteDraft.trim() || null)}
            disabled={saving}
            className="font-mono text-xs text-accent hover:underline cursor-pointer shrink-0 mt-1"
          >
            Save
          </button>
        </div>
      )}
    </div>
  );
}

// `source` on a FieldResult is prose citation text (e.g. "Terms of Tender
// (Supplement) Paragraph 10(a)-(b)"), not a resolved page/box - unlike the
// FILES section below (which points at a real resolved vendor page), this
// stays plain text.
// A redacted field's `value` is null too (there's nothing legible to
// transcribe behind the black bar) - formatValue alone would render that as
// "— blank —", which reads as "nothing was ever filled in" and directly
// contradicts "(redacted)" sitting right next to it. Redacted means the
// opposite: something IS there, it just can't be read from this copy.
function fieldValueDisplay(field) {
  return field.redacted ? "content present, redacted in this copy" : formatValue(field.value);
}

// Three distinct questions, each its own labeled block instead of running
// together as one paragraph: the field name (heading, above) is what we're
// checking for; SHOWN is what the extraction actually found; WHY FLAGGED is
// the reason a status other than plain pass was assigned. Previously SHOWN
// and WHY FLAGGED had no labels of their own and sat back-to-back with the
// same text styling, which read as one undifferentiated blob - found from
// direct user feedback on a redacted field where "— blank —" (SHOWN) sitting
// right above "is filled but redacted..." (WHY FLAGGED) looked contradictory
// rather than like two separate facts.
// font-semibold + a slightly darker ink than the value/note below (which
// stay regular-weight) so the label reads as a heading at a glance instead
// of blending into the sentence beneath it - the previous ink-4/regular-
// weight label was too close in visual weight to the content to register as
// a label at all on first read (direct user feedback: "hard to tell title
// from content"). The left rule ties each label to its own content as one
// visually bounded unit, and separates it from the next label+content pair.
function FieldMicroLabel({ children }) {
  return <p className="font-mono text-[10px] font-semibold text-ink-3 uppercase tracking-wider mb-1">{children}</p>;
}

function FieldRow({ field, letter, statusLabels, review, onDecision, mathCheck }) {
  return (
    <div className="p-2.5 border border-border-soft rounded bg-faint">
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="text-xs font-medium text-ink-2">{field.field}</span>
        <Badge kind={field.status} label={statusLabels[field.status]} />
      </div>
      <div className="mb-2 pl-2 border-l-2 border-border-soft">
        <FieldMicroLabel>Shown</FieldMicroLabel>
        <p className={`font-mono text-xs ${field.redacted ? "text-rectifiable" : "text-ink-3"}`}>
          {fieldValueDisplay(field)}
        </p>
      </div>
      {field.note && (
        <div className="mb-2 pl-2 border-l-2 border-border-soft">
          <FieldMicroLabel>Why flagged</FieldMicroLabel>
          <p className="text-xs leading-5 text-ink-2">{field.note}</p>
        </div>
      )}
      {field.status === "dormant" && field.follow_up && (
        <div className="mt-1.5 p-2 bg-bg rounded border border-border text-xs text-ink-3 leading-5">
          <p>
            <span className="font-mono text-ink-4">TRIGGER </span>
            {field.follow_up.trigger}
          </p>
          <p>
            <span className="font-mono text-ink-4">DEADLINE </span>
            {field.follow_up.computed_deadline ?? field.follow_up.deadline}
          </p>
          <p>
            <span className="font-mono text-ink-4">IF MISSED </span>
            {field.follow_up.if_deadline_missed}
          </p>
        </div>
      )}
      {field.source && <p className="font-mono text-xs text-ink-4 mt-1">{field.source}</p>}
      {/* The (A)x(B) comparison belongs to this specific field, not the item as
          a whole - attached here instead of as a separate page-level block so
          it doesn't duplicate this row's own reported-value/status (previously
          shown twice: once here, once in a floating box above the whole
          Stage I list, which also read as misplaced relative to its own
          field). field_id is this checker's own stable key, not a guess. */}
      {field.field_id === "estimated_goods_price" && <MathCheckBlock mc={mathCheck} />}
      {/* Only fields the engine itself flagged need a reviewer follow-up -
          pass/disqualified/dormant are already a settled machine verdict,
          nothing for a human to confirm/reject/note. */}
      {onDecision && field.status === "needs_review" && (
        <FieldDecisionControls field={field} letter={letter} review={review} onDecision={onDecision} />
      )}
    </div>
  );
}

function FieldGroup({ title, fields, letter, statusLabels, fieldReviews, onDecision, mathCheck }) {
  const [expanded, setExpanded] = useState(false);
  if (fields.length === 0) return null;
  const active = fields.filter((f) => f.status !== "dormant");
  const dormant = fields.filter((f) => f.status === "dormant");
  return (
    <div className="mb-3">
      <p className="font-mono text-xs text-ink-4 uppercase tracking-wider mb-1.5">
        {title} · {fields.length} field{fields.length === 1 ? "" : "s"}
      </p>
      <div className="flex flex-col gap-1.5">
        {active.map((f) => (
          <FieldRow
            key={f.field_id}
            field={f}
            letter={letter}
            statusLabels={statusLabels}
            review={fieldReviews?.[`${letter}:${f.field_id}`]}
            onDecision={onDecision}
            mathCheck={mathCheck}
          />
        ))}
      </div>
      {dormant.length > 0 && (
        <div className="mt-1.5">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="font-mono text-xs text-ink-4 hover:text-ink-2 cursor-pointer"
          >
            {expanded ? "▾" : "▸"} {dormant.length} not yet required
          </button>
          {expanded && (
            <div className="flex flex-col gap-1.5 mt-1.5">
              {dormant.map((f) => (
                <FieldRow
                  key={f.field_id}
                  field={f}
                  letter={letter}
                  statusLabels={statusLabels}
                  review={fieldReviews?.[`${letter}:${f.field_id}`]}
                  onDecision={onDecision}
                  mathCheck={mathCheck}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MathCheckBlock({ mc }) {
  if (!mc) return null;
  return (
    <div className="mt-1.5 p-2 bg-bg rounded border border-border">
      <p className="font-mono text-xs text-ink-4 mb-1">PRICE MATH · {mc.formula}</p>
      <p className="text-xs text-ink-3">
        {mc.estimated_quantity_kg ?? "—"} kg × HK${mc.one_time_unit_price_hkd ?? "—"} = expected HK$
        {mc.expected_estimated_goods_price_hkd ?? "—"}, reported HK${mc.reported_estimated_goods_price_hkd ?? "—"}
      </p>
      <p
        className={`text-xs font-mono mt-1 ${
          mc.matches === false ? "text-mandatory" : mc.matches === true ? "text-ok" : "text-ink-4"
        }`}
      >
        {mc.matches === null
          ? "not comparable — a value is missing"
          : mc.matches
            ? "✓ matches"
            : `✕ differs by HK$${mc.difference_hkd}`}
      </p>
    </div>
  );
}

function DosageAdjustmentsBlock({ da }) {
  if (!da || (!da.range_resolved && !da.rounding_applied)) return null;
  return (
    <div className="mb-3 p-3 bg-bg rounded border border-border">
      <p className="font-mono text-xs text-ink-4 mb-1">DOSAGE AUTO-ADJUSTMENT</p>
      <p className="text-xs text-ink-3">
        {da.range_resolved && (
          <>
            Range {da.raw_value}–{da.raw_max_value} resolved to the smaller value, {da.effective_value}.{" "}
          </>
        )}
        {da.rounding_applied && <>Rounded to {da.significant_figures_rounded_value} (≤2 significant figures).</>}
      </p>
    </div>
  );
}

function SelfEntryRow({ label, check }) {
  if (!check || !check.applicable) return null;
  return (
    <p className="text-xs text-ink-3 mb-1.5">
      <span className="font-mono text-ink-4">{label} </span>
      {check.matches === null
        ? "not comparable"
        : check.matches
          ? "✓ matches the Tenderer's own entry"
          : "✕ does not match the Tenderer's own entry"}
    </p>
  );
}

function PackingBlock({ pk }) {
  if (!pk || !pk.applies) return null;
  return (
    <div className="mb-3 p-3 bg-bg rounded border border-border">
      <p className="font-mono text-xs text-ink-4 mb-1">PACKING RANGE · the plant ONLY</p>
      <p className="text-xs text-ink-3">
        {pk.filled ? `${pk.value_kg} kg` : "blank"} — expected {pk.expected_min_kg}–{pk.expected_max_kg} kg.{" "}
        {pk.within_range === null ? "" : pk.within_range ? "✓ within range" : "✕ out of range"}
      </p>
    </div>
  );
}

const STATUS_SEVERITY = { pass: 0, needs_review: 1, disqualified: 2 };

// Same severity rule the backend's own worst_status/overall_status use
// (field_result.py), recomputed here because that backend rollup spans
// BOTH stages - this page only wants the stage it's showing. Dormant is
// excluded from the comparison (same as the backend), and an empty/
// all-dormant set defaults to "pass" - "nothing outstanding" reads the
// same whether that's because everything passed or because nothing in
// this stage applies yet.
export function stageRollup(fields, stage) {
  const inStage = fields.filter((f) => (stage === "II" ? f.stage === "II" : f.stage !== "II"));
  const counts = { pass: 0, needs_review: 0, disqualified: 0, dormant: 0 };
  let worst = "pass";
  inStage.forEach((f) => {
    counts[f.status] = (counts[f.status] ?? 0) + 1;
    if (f.status !== "dormant" && (STATUS_SEVERITY[f.status] ?? 0) > (STATUS_SEVERITY[worst] ?? 0)) {
      worst = f.status;
    }
  });
  return { status: worst, counts };
}

// The per-item breakdown for the Vendor Check screen - deliberately mirrors
// RequirementDetail's CollapsibleSection pattern (same component, same
// closed-by-default behavior) so moving from the Requirements tab to this
// one reads as the same screen, one level deeper: FILES (where the checker
// looked), RULES (what it checked), REFERENCES (the same paragraph
// citations Window1 already resolves for this item).
export default function VendorItemDetail({
  item,
  letter,
  checkResult,
  statusLabels,
  onViewReference,
  stageFilter,
  fieldReviews,
  onFieldDecision,
}) {
  const isPriceSchedule = letter === "b" || letter === "c";
  const isParticularsOfGoods = letter === "d" || letter === "e";
  const fields = checkResult?.fields ?? [];
  const stage1Fields = fields.filter((f) => f.stage !== "II");
  const stage2Fields = fields.filter((f) => f.stage === "II");
  // Bespoke per-checker blocks (price math, dosage adjustments, self-entry,
  // packing range) show on the Stage I page only - they read as
  // completeness/consistency information tied to the item as a whole; the
  // one Stage II-tagged field each of them touches still shows up correctly
  // in the Stage II field list regardless of whether its block renders here.
  const showBespokeBlocks = stageFilter !== "II";
  const rollup = checkResult ? stageRollup(fields, stageFilter ?? "I") : null;

  return (
    <>
      <CollapsibleSection title="Files" defaultOpen>
        {!checkResult ? (
          <p className="text-xs text-ink-4">Not checked yet — click "Run check" above.</p>
        ) : (checkResult.resolved_pages ?? []).length > 0 ? (
          <div className="flex flex-col gap-1.5">
            {checkResult.resolved_pages.map((page, i) => (
              <button
                key={`${page.source_file}-${page.page_number}-${i}`}
                type="button"
                onClick={() => onViewReference([page], `${item.id} — vendor submission, p.${page.page_number}`)}
                className="flex items-center justify-between gap-2 px-2.5 py-2 border border-border-soft rounded
                  bg-faint text-left w-full transition-colors cursor-pointer hover:border-border
                  focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
              >
                <span className="text-xs text-ink-2 truncate">{page.source_file}</span>
                <span className="font-mono text-xs text-accent-strong shrink-0">p.{page.page_number} →</span>
              </button>
            ))}
            {checkResult.literal_title_match === false && (
              <p className="text-xs text-rectifiable leading-5 mt-0.5">
                Matched by the model's semantic judgment, not a literal page-title match — this class of match has
                proven non-reproducible on repeat runs. Verify the page above is actually correct.
                {checkResult.reasoning ? ` (${checkResult.reasoning})` : ""}
              </p>
            )}
          </div>
        ) : (
          <p className="text-xs text-ink-4">
            No matching page found in the vendor's submission.
            {checkResult.reasoning ? ` ${checkResult.reasoning}` : ""}
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection title="Rules" defaultOpen>
        {!checkResult ? (
          <p className="text-xs text-ink-4">Not checked yet — click "Run check" above.</p>
        ) : !checkResult.available ? (
          <p className="text-xs text-ink-4">{checkResult.reason}</p>
        ) : (
          <div>
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <Badge kind={rollup.status} label={statusLabels[rollup.status]} />
              <span className="font-mono text-xs text-ink-4">
                {rollup.counts.pass ?? 0} pass · {rollup.counts.needs_review ?? 0} needs review ·{" "}
                {rollup.counts.disqualified ?? 0} disqualifying · {rollup.counts.dormant ?? 0} dormant
              </span>
            </div>

            {showBespokeBlocks && isPriceSchedule && <DosageAdjustmentsBlock da={checkResult.optimal_dosage_adjustments} />}
            {showBespokeBlocks && isPriceSchedule && checkResult.auto_adjustments?.length > 0 && (
              <div className="mb-3 p-3 bg-bg rounded border border-border-soft">
                <p className="font-mono text-xs text-ink-4 mb-1">AUTO-ADJUSTMENTS APPLIED</p>
                <ul className="text-xs text-ink-3 list-disc list-inside">
                  {checkResult.auto_adjustments.map((a, i) => (
                    <li key={i}>{a}</li>
                  ))}
                </ul>
              </div>
            )}
            {showBespokeBlocks && isParticularsOfGoods && (
              <div className="mb-3">
                <SelfEntryRow label="Manufacturer name self-entry" check={checkResult.name_of_manufacturer_self_entry} />
                <SelfEntryRow
                  label="Manufacturing plant address self-entry"
                  check={checkResult.address_of_manufacturing_plant_self_entry}
                />
                <PackingBlock pk={checkResult.packing_plant} />
              </div>
            )}

            {(!stageFilter || stageFilter === "I") && (
              <FieldGroup
                title="Stage I — Completeness"
                fields={stage1Fields}
                letter={letter}
                statusLabels={statusLabels}
                fieldReviews={fieldReviews}
                onDecision={onFieldDecision}
                mathCheck={isPriceSchedule ? checkResult.math_check : null}
              />
            )}
            {(!stageFilter || stageFilter === "II") && (
              <FieldGroup
                title="Stage II — Essential Requirements"
                fields={stage2Fields}
                letter={letter}
                statusLabels={statusLabels}
                fieldReviews={fieldReviews}
                onDecision={onFieldDecision}
              />
            )}
          </div>
        )}
      </CollapsibleSection>

      {item.references_paragraphs.length > 0 && (
        <CollapsibleSection title="References">
          <div className="flex flex-col gap-1">
            {item.references_paragraphs.map((ref) => {
              const resolved = ref.pages.length > 0;
              return (
                <button
                  type="button"
                  key={ref.descriptor}
                  disabled={!resolved}
                  onClick={() => onViewReference(ref.pages, ref.descriptor)}
                  className={`flex items-center justify-between gap-2 px-2.5 py-2 border border-border-soft rounded
                    bg-faint text-left w-full transition-colors
                    ${resolved ? "cursor-pointer hover:border-border" : "cursor-not-allowed opacity-60"}
                    focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2`}
                >
                  <span className="font-mono text-xs font-medium text-accent-strong min-w-0">{ref.descriptor}</span>
                  <span className="font-mono text-xs text-ink-4 shrink-0">
                    {resolved ? `p.${ref.pages[0].page_number} →` : "unresolved"}
                  </span>
                </button>
              );
            })}
          </div>
        </CollapsibleSection>
      )}
    </>
  );
}

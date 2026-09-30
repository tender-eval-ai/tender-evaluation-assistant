import { useCallback, useEffect, useMemo, useState } from "react";
import {
  addRulesetItem,
  confirmRuleset,
  reevaluate,
  deleteRulesetItem,
  getActingUser,
  getRuleset,
  listDocuments,
  listRulesetGaps,
  listRulesetVersions,
  patchRulesetItem,
  putRulesetDraft,
  setActingUser,
  USE_MOCK,
} from "../api.js";
import { tenderPage } from "../citations.js";
import DocumentViewer from "../components/DocumentViewer.jsx";
import RequirementCard from "../components/RequirementCard.jsx";
import AddItemForm from "../components/rules/AddItemForm.jsx";
import DiffPanel from "../components/rules/DiffPanel.jsx";
import DraftJsonEditor from "../components/rules/DraftJsonEditor.jsx";
import GapsPanel from "../components/rules/GapsPanel.jsx";
import { ApiErrorText, buttonCls, inputCls, quietButtonCls } from "../components/rules/ReasonForm.jsx";
import RuleItemDetail from "../components/rules/RuleItemDetail.jsx";
import { blockers, when } from "../components/rules/values.js";

const TIER_LABEL = { A: "Mandatory", B: "Rectifiable", C: "Discretionary" };
const PART_NOTE = {
  A: "Missing = not considered further",
  B: "Missing = may be requested before disqualifying",
  C: "Discretionary",
};

// Why POST /confirm refused, for a person: 403 self_approval names who must
// not confirm; 409 conflict lists what still blocks, with a way to it.
function ConfirmError({ error, draft, onOpenItem, onOpenGaps }) {
  if (!error) return null;
  if (error.code === "self_approval") {
    return (
      <div role="alert" className="mt-2 px-2.5 py-2 rounded border border-mandatory/40 bg-mandatory-wash text-xs text-mandatory">
        <p className="font-medium">You made the last change to draft v{draft?.version}, so you cannot confirm it.</p>
        <p className="mt-0.5">Another person reviews and confirms it (four eyes). The API said: {error.message}</p>
      </div>
    );
  }
  if (error.code === "conflict") {
    const { items, gaps } = blockers(draft);
    if (items.length || gaps.length) {
      return (
        <div role="alert" className="mt-2 px-2.5 py-2 rounded border border-mandatory/40 bg-mandatory-wash text-xs text-mandatory">
          <p className="font-medium">Draft v{draft.version} cannot be confirmed yet:</p>
          <ul className="list-disc pl-4 mt-1 space-y-0.5">
            {items.map((i) => (
              <li key={i.letter}>
                <button type="button" className="underline cursor-pointer" onClick={() => onOpenItem(i.letter)}>
                  item ({i.letter}) {i.status === "gap" ? "has no rule" : "needs input"}
                </button>
              </li>
            ))}
            {gaps.map((g) => (
              <li key={g.node_id}>
                <button type="button" className="underline cursor-pointer" onClick={onOpenGaps}>
                  gap {g.node_id} has no reason
                </button>
              </li>
            ))}
          </ul>
        </div>
      );
    }
  }
  return (
    <div className="mt-2">
      <ApiErrorText error={error} />
    </div>
  );
}

const TABS = [
  ["items", "Items"],
  ["gaps", "Gaps"],
  ["diff", "Changes"],
  ["json", "JSON"],
];

// The Rules window: the project's rule set read against the tender, and
// edited. Every change is a versioned, attributed record with a reason; the
// model's value stays beside a person's correction; the person who changed a
// draft last cannot confirm it.
export default function RulesWindow({ projectId, tierFilter = "all", onCountsChange, onConfirmed }) {
  const [latest, setLatest] = useState(null);
  const [versions, setVersions] = useState([]);
  const [gaps, setGaps] = useState(null);
  const [documents, setDocuments] = useState(null);
  const [older, setOlder] = useState(null); // an older version being read, else null
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("items");
  const [activeLetter, setActiveLetter] = useState(null);
  const [adding, setAdding] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [actingAs, setActingAs] = useState(getActingUser());
  const [viewer, setViewer] = useState({ file: null, label: null, pages: [], focus: null });

  const refresh = useCallback(
    () =>
      Promise.all([getRuleset(projectId), listRulesetVersions(projectId), listRulesetGaps(projectId)]).then(
        ([rs, vs, gs]) => {
          setLatest(rs);
          setVersions(vs);
          setGaps(gs);
          setOlder(null);
          setRevision((r) => r + 1);
          return rs;
        }
      ),
    [projectId]
  );

  useEffect(() => {
    let cancelled = false;
    setLatest(null);
    setError(null);
    Promise.all([refresh(), listDocuments(projectId)])
      .then(([rs, docs]) => {
        if (cancelled) return;
        setDocuments(docs);
        setActiveLetter(rs.items[0]?.letter ?? null);
      })
      .catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [projectId, refresh]);

  const shown = older ?? latest;
  const editable = Boolean(shown && latest && shown.version === latest.version);

  const items = useMemo(
    () => (shown?.items ?? []).map((item) => ({ ...item, id: item.letter, displayId: `(${item.letter})` })),
    [shown]
  );
  const active = items.find((i) => i.letter === activeLetter) ?? null;

  const tierCounts = useMemo(() => {
    const c = { all: items.length, A: 0, B: 0, C: 0 };
    items.forEach((i) => {
      if (c[i.part] !== undefined) c[i.part]++;
    });
    return c;
  }, [items]);

  const countsKey = `${tierCounts.all}-${tierCounts.A}-${tierCounts.B}-${tierCounts.C}`;
  useEffect(() => {
    if (onCountsChange) onCountsChange(tierCounts);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [countsKey]);

  function viewCitation(citation, label) {
    if (!citation || !documents) return;
    tenderPage(projectId, documents, citation)
      .then((page) => setViewer({ file: page.file, label, pages: [page], focus: page.pageNumber }))
      .catch((err) => setNotice({ error: err.message }));
  }

  useEffect(() => {
    if (active && documents) viewCitation(active.citation, `(${active.letter}) — schedule row`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.letter, documents]);

  function pickVersion(n) {
    setConfirmError(null);
    if (n === latest.version) {
      setOlder(null);
      return;
    }
    getRuleset(projectId, { version: n })
      .then(setOlder)
      .catch((err) => setNotice({ error: err.message }));
  }

  function changeUser(name) {
    setActingAs(name);
    setActingUser(name);
    setConfirmError(null);
  }

  // Every mutation reloads the latest version, so the list, the version
  // picker and the blockers stay the API's.
  const after = (message) => (result) =>
    refresh().then(() => {
      setConfirmError(null);
      setNotice({ ok: message });
      return result;
    });

  const patchItem = (letter, patch) =>
    patchRulesetItem(projectId, letter, patch).then(after(`Item (${letter}) saved, with your reason.`));

  const deleteItem = (letter, reason) =>
    deleteRulesetItem(projectId, letter, reason)
      .then(after(`Item (${letter}) deleted.`))
      .then(() => setActiveLetter(null));

  const addItem = (newItem) =>
    addRulesetItem(projectId, newItem)
      .then(after("Item added."))
      .then((item) => {
        setAdding(false);
        setActiveLetter(item.letter);
      });

  const saveGapReason = (nodeId, reason) =>
    putRulesetDraft(projectId, {
      ...latest,
      gaps: latest.gaps.map((g) => (g.node_id === nodeId ? { ...g, reason } : g)),
    }).then(after(`Reason saved for gap ${nodeId}.`));

  const saveGapReasons = (nodeIds, reason) =>
    putRulesetDraft(projectId, {
      ...latest,
      gaps: latest.gaps.map((g) => (nodeIds.includes(g.node_id) ? { ...g, reason } : g)),
    }).then(after(`Reason saved for ${nodeIds.length} gaps.`));

  const saveDraft = (draft) => putRulesetDraft(projectId, draft).then(after("Draft saved."));

  // Re-deciding every checked tenderer against a confirmed version. Offered rather
  // than run automatically, because a result whose verdict changes loses its review
  // confirmation - a reviewer should choose that moment.
  function handleReevaluate() {
    setNotice(null);
    setConfirmError(null);
    reevaluate(projectId, { version: shown.version })
      .then(() => setNotice({ ok: `Re-evaluating every checked tenderer against v${shown.version}. `
        + "A result whose verdict changes loses its review confirmation." }))
      .catch((err) => setNotice({ error: err.message }));
  }

  function handleConfirm() {
    setConfirming(true);
    setConfirmError(null);
    setNotice(null);
    confirmRuleset(projectId)
      .then((rs) => refresh().then(() => onConfirmed?.(rs)))
      .catch(setConfirmError)
      .finally(() => setConfirming(false));
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-mandatory p-10 text-center">
        Failed to load: {error}
      </div>
    );
  }
  if (!latest) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-ink-3 p-10 text-center">
        Loading the rule set…
      </div>
    );
  }

  const visible = tierFilter === "all" ? items : items.filter((i) => i.part === tierFilter);
  const parts = ["A", "B", "C"].filter((p) => visible.some((i) => i.part === p));
  const block = blockers(latest);
  const openGaps = (gaps ?? []).filter((g) => !g.reason).length;
  const parentOfLatest = latest.parent_version ?? versions.at(-2)?.version ?? latest.version;

  return (
    <div className="flex-1 flex overflow-hidden min-h-0">
      {/* LEFT — source document */}
      <div className="w-[30%] min-w-0 border-r border-border flex flex-col overflow-hidden bg-bg">
        <div className="px-3 py-2.5 border-b border-border bg-card shrink-0">
          <p className="font-mono text-xs text-ink-4 uppercase tracking-wider">Source document</p>
          <p className="text-xs font-semibold text-accent-strong truncate mt-0.5">{viewer.file ?? "—"}</p>
          <p className="text-xs text-ink-4 truncate">{viewer.label ?? ""}</p>
        </div>
        <DocumentViewer pages={viewer.pages} focusPage={viewer.focus} emptyLabel="Select a requirement to see its source page." />
      </div>

      <div className="flex-1 min-w-0 flex flex-col overflow-hidden bg-card">
        {/* The rule set's header: version, confirmation, who is acting. */}
        <div className="px-3 py-2.5 border-b border-border bg-bg shrink-0">
          <div className="flex items-center gap-3 flex-wrap">
            <label className="flex items-center gap-1.5 font-mono text-xs text-ink-4 uppercase tracking-wider">
              Rule set
              <select
                aria-label="Rule set version"
                value={shown.version}
                onChange={(e) => pickVersion(Number(e.target.value))}
                className={`${inputCls} w-auto normal-case tracking-normal`}
              >
                {[...versions].reverse().map((v) => (
                  <option key={v.version} value={v.version}>
                    v{v.version} · {v.status}
                    {v.version === latest.version ? " (latest)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <span className="font-mono text-xs text-ink-4">
              {items.length} item{items.length === 1 ? "" : "s"}
              {shown.parent_version ? ` · from v${shown.parent_version}` : ""}
            </span>
            {shown.status === "confirmed" && (
              <button
                type="button"
                onClick={handleReevaluate}
                className="font-mono text-xs text-accent hover:underline cursor-pointer"
              >
                re-evaluate every tenderer against v{shown.version}
              </button>
            )}
            {USE_MOCK && (
              <label
                className="flex items-center gap-1.5 text-xs text-ink-4 ml-auto"
                title="Sent as X-User. Mock only: edit as one person, confirm as another."
              >
                acting as
                <input aria-label="Acting user" value={actingAs} onChange={(e) => changeUser(e.target.value)} className={`${inputCls} w-28 font-mono`} />
              </label>
            )}
          </div>

          <div className="mt-2 flex items-center gap-3 flex-wrap">
            {shown.status === "confirmed" ? (
              <p className="font-mono text-xs text-ok">
                ✓ v{shown.version} confirmed by {shown.confirmed_by}
                {shown.confirmed_at ? ` · ${when(shown.confirmed_at)}` : ""}
                {editable ? " · an edit opens a new draft" : ""}
              </p>
            ) : editable ? (
              <>
                <button type="button" disabled={confirming} onClick={handleConfirm} className={buttonCls}>
                  {confirming ? "confirming…" : `✓ Confirm draft v${latest.version}`}
                </button>
                <span className="text-xs text-ink-4">
                  {block.items.length || block.gaps.length
                    ? `Blocked by ${[
                        block.items.length && `${block.items.length} item${block.items.length > 1 ? "s" : ""} needing input`,
                        block.gaps.length && `${block.gaps.length} gap${block.gaps.length > 1 ? "s" : ""} without a reason`,
                      ]
                        .filter(Boolean)
                        .join(" and ")}`
                    : "Ready: a person other than the last editor confirms it."}
                </span>
              </>
            ) : (
              <p className="font-mono text-xs text-ink-4">v{shown.version} · draft</p>
            )}
            {!editable && (
              <button type="button" className={quietButtonCls} onClick={() => pickVersion(latest.version)}>
                read only · back to v{latest.version}
              </button>
            )}
          </div>
          <ConfirmError
            error={confirmError}
            draft={latest}
            onOpenItem={(letter) => {
              setTab("items");
              setAdding(false);
              setActiveLetter(letter);
            }}
            onOpenGaps={() => setTab("gaps")}
          />
          {notice?.ok && <p className="mt-2 text-xs text-ok">{notice.ok}</p>}
          {notice?.error && <p className="mt-2 text-xs text-mandatory">{notice.error}</p>}
        </div>

        <div role="tablist" className="flex gap-1 px-3 pt-2 border-b border-border bg-bg shrink-0">
          {TABS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={`px-2.5 py-1 text-xs font-mono rounded-t border border-b-0 cursor-pointer ${
                tab === key ? "bg-card border-border text-accent-strong" : "border-transparent text-ink-3 hover:text-ink"
              }`}
            >
              {label}
              {key === "gaps" && openGaps > 0 && editable ? ` · ${openGaps} open` : ""}
            </button>
          ))}
        </div>

        {tab === "items" && (
          <div className="flex-1 flex overflow-hidden min-h-0">
            {/* CENTRE — the rule set's items, by Part */}
            <div className="w-[45%] min-w-0 border-r border-border flex flex-col overflow-hidden">
              {editable && (
                <div className="px-2.5 pt-2.5 shrink-0">
                  <button type="button" className={quietButtonCls} onClick={() => setAdding(true)}>
                    + add an item from a clause
                  </button>
                </div>
              )}
              <div className="flex-1 overflow-y-auto p-2.5 flex flex-col gap-1.5" data-testid="rule-items">
                {parts.map((part) => (
                  <div key={part} className="flex flex-col gap-1.5">
                    <div className="flex items-baseline gap-2 pt-1">
                      <span className="font-mono text-xs font-semibold uppercase tracking-wider text-ink-3">
                        {TIER_LABEL[part] ?? part}
                      </span>
                      <span className="text-xs text-ink-4 truncate">{PART_NOTE[part]}</span>
                    </div>
                    {visible
                      .filter((i) => i.part === part)
                      .map((item) => (
                        <RequirementCard
                          key={item.id}
                          item={item}
                          isActive={!adding && item.letter === activeLetter}
                          onSelect={(i) => {
                            setAdding(false);
                            setActiveLetter(i.letter);
                          }}
                        />
                      ))}
                  </div>
                ))}
              </div>
            </div>

            {/* RIGHT — the item, editable */}
            <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
              {adding ? (
                <AddItemForm
                  documents={documents}
                  dataClass={latest.data_class}
                  initial={viewer.file ? { file: viewer.file, page: viewer.focus } : null}
                  onSubmit={addItem}
                  onCancel={() => setAdding(false)}
                />
              ) : (
                <RuleItemDetail
                  key={`${shown.version}-${active?.letter}`}
                  item={active}
                  editable={editable}
                  onViewReference={viewCitation}
                  onPatch={patchItem}
                  onDelete={deleteItem}
                />
              )}
            </div>
          </div>
        )}

        {tab === "gaps" && <GapsPanel gaps={editable ? gaps : shown.gaps} editable={editable} onSaveReason={saveGapReason}
                                     onSaveReasons={saveGapReasons} />}

        {tab === "diff" && (
          <DiffPanel
            key={revision}
            projectId={projectId}
            versions={versions}
            initialFrom={older ? (older.parent_version ?? older.version) : parentOfLatest}
            initialTo={shown.version}
          />
        )}

        {tab === "json" && (
          <DraftJsonEditor key={`${revision}-${shown.version}`} ruleset={shown} editable={editable} onSave={saveDraft} />
        )}
      </div>
    </div>
  );
}

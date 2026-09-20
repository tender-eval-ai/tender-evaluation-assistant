import { useState } from "react";
import ReasonForm, { inputCls, monoInputCls, quietButtonCls } from "./ReasonForm.jsx";
import { defaultRule } from "./values.js";

// Add an item from a clause of the tender (POST .../ruleset/items). The clause
// becomes the item's citation. Page images carry no text layer, so the
// selection is picked here: the document and page (the viewer's current page
// by default) and the clause as printed, typed or taken from text selected
// anywhere in the window.
export default function AddItemForm({ documents, dataClass, initial, onSubmit, onCancel }) {
  const tenderDocs = (documents ?? []).filter((d) => d.kind === "tender");
  const [title, setTitle] = useState("");
  const [part, setPart] = useState("B");
  const [file, setFile] = useState(initial?.file ?? tenderDocs[0]?.file ?? "");
  const [page, setPage] = useState(initial?.page ?? 1);
  const [nodeId, setNodeId] = useState("");
  const [quote, setQuote] = useState(initial?.quote ?? "");

  const doc = tenderDocs.find((d) => d.file === file);
  const pageOk = Number.isInteger(Number(page)) && Number(page) >= 1 && (!doc || Number(page) <= doc.pages);
  const ready = title.trim() && quote.trim() && doc && pageOk;

  function takeSelection() {
    const text = window.getSelection?.()?.toString().trim();
    if (text) setQuote(text);
  }

  function submit(reason) {
    return onSubmit({
      title: title.trim(),
      part,
      citation: {
        file: `tender/${file}`,
        page: Number(page),
        node_id: nodeId.trim() || null,
        quote: quote.trim(),
        data_class: dataClass,
      },
      rules: [defaultRule(title, part)],
      reason,
    });
  }

  return (
    <div className="flex-1 overflow-y-auto p-4">
      <ReasonForm title="Add an item from a clause" submitLabel="Add the item" canSubmit={Boolean(ready)} onSubmit={submit} onCancel={onCancel}>
        <label className="flex flex-col gap-1 text-xs text-ink-3">
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} className={inputCls} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-ink-3">
          Part
          <select value={part} onChange={(e) => setPart(e.target.value)} className={inputCls}>
            <option value="A">A — missing: not considered further</option>
            <option value="B">B — missing: may be requested</option>
            <option value="C">C — discretionary</option>
          </select>
        </label>
        <fieldset className="flex flex-col gap-2 p-2 border border-border-soft rounded">
          <legend className="px-1 font-mono text-xs text-ink-4 uppercase tracking-wider">Citation — the selected clause</legend>
          <label className="flex flex-col gap-1 text-xs text-ink-3">
            Document
            <select value={file} onChange={(e) => setFile(e.target.value)} className={inputCls}>
              {tenderDocs.map((d) => (
                <option key={d.doc_id} value={d.file}>
                  {d.file}
                </option>
              ))}
            </select>
          </label>
          <div className="flex gap-2">
            <label className="flex flex-col gap-1 text-xs text-ink-3 w-24">
              Page
              <input type="number" min={1} max={doc?.pages} value={page} onChange={(e) => setPage(e.target.value)} className={monoInputCls} />
            </label>
            <label className="flex flex-col gap-1 text-xs text-ink-3 flex-1">
              Clause node (optional)
              <input value={nodeId} onChange={(e) => setNodeId(e.target.value)} placeholder="e.g. Supp:13:(d)" className={monoInputCls} />
            </label>
          </div>
          {!pageOk && <p className="text-xs text-mandatory">{doc?.file} has pages 1 to {doc?.pages}.</p>}
          <label className="flex flex-col gap-1 text-xs text-ink-3">
            Clause text, verbatim
            <textarea rows={3} value={quote} onChange={(e) => setQuote(e.target.value)} className={inputCls} />
          </label>
          <button
            type="button"
            // Keep the page's text selection: a mousedown here would clear it.
            onMouseDown={(e) => e.preventDefault()}
            onClick={takeSelection}
            className={`${quietButtonCls} self-start`}
          >
            use selected text
          </button>
        </fieldset>
        <p className="text-xs text-ink-4">
          Starts with one rule, “the document is present”, with Part {part}’s outcome when it is missing. Edit the
          rules once the item is added.
        </p>
      </ReasonForm>
    </div>
  );
}

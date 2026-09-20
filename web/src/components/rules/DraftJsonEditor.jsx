import { useState } from "react";
import { ApiErrorText, buttonCls, monoInputCls, quietButtonCls } from "./ReasonForm.jsx";

// The whole draft as JSON (PUT .../ruleset/draft). The API validates it
// against app/rulesets/schema.py and answers 422 validation_failed with each
// error's location; they are listed under the editor.
export default function DraftJsonEditor({ ruleset, editable, onSave }) {
  const [text, setText] = useState(() => JSON.stringify(ruleset, null, 2));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  let parseError = null;
  try {
    JSON.parse(text);
  } catch (err) {
    parseError = err.message;
  }

  function save() {
    setBusy(true);
    setError(null);
    // On success the window reloads the draft and remounts this editor.
    onSave(JSON.parse(text))
      .catch(setError)
      .finally(() => setBusy(false));
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden p-4 gap-2">
      <p className="text-xs text-ink-3">
        The whole draft, as the API stores it. The server sets the version, the status and who confirmed it.
        {!editable && " This is an older version: read only."}
      </p>
      <textarea
        aria-label="Rule set JSON"
        value={text}
        onChange={(e) => setText(e.target.value)}
        readOnly={!editable}
        spellCheck={false}
        className={`${monoInputCls} flex-1 min-h-[240px] resize-none`}
      />
      {parseError && <p className="text-xs text-mandatory">Not valid JSON: {parseError}</p>}
      <ApiErrorText error={error} />
      {editable && (
        <div className="flex gap-2">
          <button type="button" className={buttonCls} disabled={Boolean(parseError) || busy} onClick={save}>
            {busy ? "saving…" : "Save the draft"}
          </button>
          <button
            type="button"
            className={quietButtonCls}
            onClick={() => {
              setText(JSON.stringify(ruleset, null, 2));
              setError(null);
            }}
          >
            Revert
          </button>
        </div>
      )}
    </div>
  );
}

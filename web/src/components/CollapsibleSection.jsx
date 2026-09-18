import { useState } from "react";
import { ChevronIcon } from "./Icons.jsx";

// Header emphasis is color (text-accent-strong), not font-weight - the
// eyebrow labels this replaces (SOURCE, METHOD, ...) were already font-mono
// uppercase, which reads as a header on its own; adding bold on top of that
// was the wrong kind of emphasis. Closed by default so a dense detail pane
// (6+ of these per item) doesn't dump everything on screen at once.
export default function CollapsibleSection({ title, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="mb-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full flex items-center gap-1.5 py-1 text-left cursor-pointer group
          focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
      >
        <ChevronIcon direction={open ? "down" : "right"} className="text-accent-strong shrink-0" />
        <span className="font-mono text-xs uppercase tracking-wider text-accent-strong group-hover:opacity-80">
          {title}
        </span>
      </button>
      {open && <div className="pl-5 pt-1 border-l border-border-soft ml-[6px]">{children}</div>}
    </div>
  );
}

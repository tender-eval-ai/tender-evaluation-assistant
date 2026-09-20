// Chrome ported from the Figma Make design: a tight 44px navy bar, small mono
// mark, low-contrast nav items that brighten on hover, and right-aligned context.
// No separate tab bar here anymore - PipelineStepper's 5-stage control is now
// the only navigation (it covered every one of these tabs already; two nav
// systems side by side was the redundancy, not either one alone).
export default function TopNav({ tenderName, dataClass, mock = false, onChangeProject, user }) {
  return (
    <header className="h-11 bg-navy flex items-center px-4 gap-5 shrink-0">
      <div className="flex items-center gap-2 shrink-0">
        <div className="w-5 h-5 bg-white/20 rounded-sm flex items-center justify-center">
          <span className="text-white text-xs font-bold font-mono">PR</span>
        </div>
        <span className="text-white text-sm font-semibold tracking-tight">Procurement Review</span>
      </div>

      <div className="ml-auto flex items-center gap-3 min-w-0">
        {mock && (
          <span className="px-1.5 py-0.5 rounded bg-white/15 text-white text-xs font-mono shrink-0" title="web/mock/">
            mock API
          </span>
        )}
        {tenderName && <span className="text-white/50 text-xs font-mono truncate">{tenderName}</span>}
        {dataClass && <span className="text-white/50 text-xs font-mono shrink-0">{dataClass}</span>}
        <button
          type="button"
          className="text-white/70 hover:text-white text-xs transition-colors cursor-pointer shrink-0"
          onClick={onChangeProject}
        >
          Change project
        </button>
        <div
          className="w-7 h-7 rounded-full bg-accent flex items-center justify-center text-white text-xs font-semibold shrink-0"
          title={user}
        >
          {String(user ?? "?").slice(0, 2).toUpperCase()}
        </div>
      </div>
    </header>
  );
}

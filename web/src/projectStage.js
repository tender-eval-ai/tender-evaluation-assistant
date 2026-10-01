// Where a project stands, for its card on the project list: finished once every tenderer
// is checked and its review confirmed; otherwise the step this browser last had open,
// so an ongoing project is easy to find again and reopens where it was left.
import { getEvaluation, getProject } from "./api.js";

export const STEPS = [
  ["rules", "Rules"],
  ["stage1", "Stage I completeness"],
  ["stage2", "Stage II compliance"],
  ["scoring", "Scoring"],
  ["report", "Report"],
];

const key = (pid) => `tender-eval:last-step:${pid}`;

// Browser storage can be missing or refuse (a private window, blocked site data). The step
// is a convenience, so a failure only means nothing is remembered.
export function rememberStep(pid, step) {
  try {
    window.localStorage.setItem(key(pid), step);
  } catch {
    /* not remembered */
  }
}

export function lastStep(pid) {
  try {
    const step = window.localStorage.getItem(key(pid));
    return STEPS.some(([k]) => k === step) ? step : null;
  } catch {
    return null;
  }
}

// { finished: true } or { finished: false, step, number, label }. Without a remembered step,
// a project with no confirmed rule set is at its rules (the evaluation answers 409), and one
// with a confirmed rule set is at its checks.
export async function projectStage(pid) {
  const evaluation = await getEvaluation(pid).catch(() => null);
  if (evaluation) {
    const bidders = (await getProject(pid).catch(() => null))?.bidders ?? [];
    const reviewed = new Set(evaluation.tenderers.filter((t) => t.reviewed_by).map((t) => t.tenderer));
    if (bidders.length > 0 && bidders.every((b) => reviewed.has(b))) return { finished: true };
  }
  const step = lastStep(pid) ?? (evaluation ? "stage1" : "rules");
  const index = STEPS.findIndex(([k]) => k === step);
  return { finished: false, step, number: index + 1, label: STEPS[index][1] };
}

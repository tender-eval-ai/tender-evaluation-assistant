// An item's status on the Stage I and Stage II pages, which has to agree with
// BidResult.stage1 / stage2 (stage_summary in app/checks/engine_bridge.py).
import { describe, expect, it } from "vitest";
import { stageStatus } from "./verdicts.js";

const check = (status, stage = "I") => ({ field_id: `x.${status}`, status, stage });
const verdict = (checks, outcome = "pass") => ({ outcome, checks });

describe("stageStatus", () => {
  it("is the worst live check at that stage", () => {
    const v = verdict([check("pass"), check("needs_review"), check("disqualified", "II"), check("pass", "II")]);
    expect(stageStatus(v, "I")).toBe("needs_review");
    expect(stageStatus(v, "II")).toBe("disqualified");
  });

  it("has none where nothing was checked at that stage, rather than a pass", () => {
    // A Stage II rule for a limit the tender doesn't set is not checked at all.
    expect(stageStatus(verdict([check("pass")]), "II")).toBeNull();
  });

  it("is dormant when everything at that stage is", () => {
    expect(stageStatus(verdict([check("dormant", "II"), check("dormant", "II")]), "II")).toBe("dormant");
    expect(stageStatus(verdict([check("dormant", "II"), check("pass", "II")]), "II")).toBe("pass");
  });

  it("needs review at Stage I for an item the engine could not check", () => {
    const blocked = verdict([], "needs_review");
    expect(stageStatus(blocked, "I")).toBe("needs_review");
    expect(stageStatus(blocked, "II")).toBeNull();
  });

  it("has none without a verdict", () => {
    expect(stageStatus(null, "I")).toBeNull();
  });
});

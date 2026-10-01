import { describe, expect, it } from "vitest";
import { principalName, signedInName } from "./api.js";

describe("the signed-in name from Azure's sign-in session", () => {
  it("takes the display name claim", () => {
    const me = [{ user_id: "someone@example.com", user_claims: [{ typ: "name", val: "Chenyu Fang" }] }];
    expect(principalName(me)).toBe("Chenyu Fang");
  });

  it("falls back to the user id before the @, never the whole address", () => {
    expect(principalName([{ user_id: "reviewer.two@example.com", user_claims: [] }])).toBe("reviewer.two");
  });

  it("is null for an empty or unexpected session", () => {
    expect(principalName([])).toBeNull();
    expect(principalName(null)).toBeNull();
    expect(principalName([{ user_claims: [] }])).toBeNull();
  });

  it("is not looked up on the mock", async () => {
    expect(await signedInName()).toBeNull();
  });
});

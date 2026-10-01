import { describe, expect, it } from "vitest";
import { signedInName } from "./api.js";

describe("the signed-in name", () => {
  it("is not looked up on the mock", async () => {
    expect(await signedInName()).toBeNull();
  });
});

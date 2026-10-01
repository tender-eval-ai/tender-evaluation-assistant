// The guest site (VITE_REPLAY=1): every GET answered from the recording's files, nothing
// changed, and page images from the recording too.
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { server } from "../mock/node.js";
import { routeKey } from "./replayKey.js";

async function replayApi() {
  vi.stubEnv("VITE_REPLAY", "1");
  vi.stubEnv("VITE_REPLAY_LABEL", "Recorded run · 1 October 2026");
  vi.resetModules();
  return import("./api.js");
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("a recorded run", () => {
  it("answers a GET from the recording's file for that path, or for the path without its query", async () => {
    const asked = [];
    server.use(http.get("*/replay/api/:key", ({ params }) => {
      asked.push(params.key);
      return params.key === routeKey("/projects/p1/ruleset") ? HttpResponse.json({ version: 2 }) : new HttpResponse(null, { status: 404 });
    }));
    const api = await replayApi();
    expect(api.REPLAY).toBe(true);
    expect(api.USE_MOCK).toBe(false);
    expect(await api.getRuleset("p1", { version: 2 })).toEqual({ version: 2 });
    expect(asked).toEqual([routeKey("/projects/p1/ruleset?version=2"), routeKey("/projects/p1/ruleset")]);
  });

  it("refuses every change, with a reason a visitor can read", async () => {
    const api = await replayApi();
    await expect(api.confirmReview("p1", "Tenderer_A")).rejects.toMatchObject({ status: 405, code: "recorded_run" });
    await expect(api.createProject("x", "synthetic")).rejects.toThrow("This is a recorded run");
  });

  it("shows page images from the recording, highlight included", async () => {
    const api = await replayApi();
    const url = api.pageImageUrl("/projects/p1/documents/d1/pages/7/image?exp=1&sig=x", { highlight: "(a) The Offer" });
    expect(url).toBe(`/replay/img/${routeKey("/projects/p1/documents/d1/pages/7/image?highlight=(a) The Offer")}.jpg`);
    expect(api.REPLAY_LABEL).toBe("Recorded run · 1 October 2026");
  });
});

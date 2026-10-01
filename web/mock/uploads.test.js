// @vitest-environment node
// The mock's upload routes with a real multipart body: jsdom's File isn't the Blob that
// Node's fetch sends, so this file runs in Node.
import { describe, expect, it } from "vitest";
import * as fx from "./fixtures.js";

const BASE = "http://api.test";

describe("uploads", () => {
  it("take PDFs and refuse anything else", async () => {
    const send = (names) => {
      const form = new FormData();
      for (const n of names) form.append("files", new File(["%PDF-1.4"], n, { type: "application/pdf" }));
      return fetch(`${BASE}/projects/${fx.PID}/bids/Tenderer_X`, { method: "POST", body: form });
    };
    expect(await (await send(["offer.pdf"])).json()).toEqual({ saved: ["offer.pdf"] });
    expect((await send(["offer.docx"])).status).toBe(400);
  });
});

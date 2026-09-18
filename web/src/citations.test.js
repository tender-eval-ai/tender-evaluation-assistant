// PageCitation (PR #35) to a DocumentViewer page, and a rule set Citation to
// its Document by path.
import { describe, expect, it } from "vitest";
import { boxOnPage, documentFor, offerPage } from "./citations.js";

const signed = "/projects/p/documents/d/pages/10/image?exp=1&sig=s&highlight=Tenderer+A";

describe("offerPage", () => {
  it("uses image_url as given and scales the box by page_size", () => {
    const page = offerPage({
      doc_id: "d", file: "offer.pdf", page: 10, image_url: signed,
      quote: "Tenderer A", box: [59.5, 84.2, 297.5, 168.4], page_size: [595, 842],
    });
    const url = new URL(page.url);
    expect(url.pathname + url.search).toBe(signed);
    expect(page.quote).toBe("Tenderer A");
    expect(page.box.left).toBeCloseTo(10);
    expect(page.box.top).toBeCloseTo(10);
    expect(page.box.width).toBeCloseTo(40);
    expect(page.box.height).toBeCloseTo(10);
  });

  it("opens the plain page when quote and box are null (a scanned page)", () => {
    const plain = "/projects/p/documents/d/pages/13/image?exp=1&sig=s";
    const page = offerPage({ doc_id: "d", file: "offer.pdf", page: 13, image_url: plain, quote: null, box: null, page_size: null });
    expect(new URL(page.url).searchParams.has("highlight")).toBe(false);
    expect(page.box).toBeNull();
    expect(page.pageNumber).toBe(13);
  });

  it("also takes a citation from before PR #35, without the three fields", () => {
    expect(offerPage({ doc_id: "d", file: "offer.pdf", page: 2, image_url: "/x?exp=1&sig=s" }).box).toBeNull();
  });
});

describe("boxOnPage", () => {
  it("is null without a usable box or page size", () => {
    expect(boxOnPage(null, [595, 842])).toBeNull();
    expect(boxOnPage([0, 0, 10, 10], null)).toBeNull();
    expect(boxOnPage([10, 10, 5, 20], [595, 842])).toBeNull();
    expect(boxOnPage([0, 0, 10, 10], [0, 842])).toBeNull();
  });
});

describe("documentFor", () => {
  const docs = [
    { doc_id: "t9", file: "09 Schedules.pdf", path: "tender/09 Schedules.pdf", kind: "tender" },
    { doc_id: "ba", file: "offer.pdf", path: "bids/Tenderer_A/offer.pdf", kind: "bid", tenderer: "Tenderer_A" },
    { doc_id: "bb", file: "offer.pdf", path: "bids/Tenderer_B/offer.pdf", kind: "bid", tenderer: "Tenderer_B" },
  ];
  it("matches Citation.file to Document.path", () => {
    expect(documentFor(docs, { file: "tender/09 Schedules.pdf" }).doc_id).toBe("t9");
    expect(documentFor(docs, { file: "bids/Tenderer_B/offer.pdf" }).doc_id).toBe("bb");
    expect(documentFor(docs, { file: "09 Schedules.pdf" })).toBeNull();
    expect(documentFor(null, { file: "tender/09 Schedules.pdf" })).toBeNull();
  });
});

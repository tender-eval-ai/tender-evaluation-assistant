import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DocumentViewer from "./DocumentViewer.jsx";

const pages = [1, 2, 3].map((n) => ({ url: `/p/${n}.png`, label: `offer.pdf, p.${n}`, pageNumber: n }));

describe("DocumentViewer", () => {
  afterEach(() => vi.restoreAllMocks());

  it("scrolls its own page stack to the cited page, never the window", () => {
    const intoView = vi.spyOn(Element.prototype, "scrollIntoView");
    const windowScroll = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    const { container } = render(<DocumentViewer pages={pages} focusPage={3} />);
    expect(intoView).not.toHaveBeenCalled();
    expect(windowScroll).not.toHaveBeenCalled();
    expect(container.querySelector(".page-stack-item-focus")?.dataset.pageNumber).toBe("3");
  });
});

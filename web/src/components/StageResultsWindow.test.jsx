// The S2 stop point on the mock: item (l) of the synthetic tender shows in the
// Stage I window with its verdict, its cited page, and the page highlighted
// through the signed image_url and the citation's box (PR #35).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { PID, TENDERERS, bidResult } from "../../mock/fixtures.js";
import StageResultsWindow from "./StageResultsWindow.jsx";

function renderStageI(tenderer) {
  return render(
    <StageResultsWindow projectId={PID} tenderer={tenderer} stage="I" title="Stage I — Completeness" pollMs={5} />
  );
}

const fixtureCitation = (t, letter, field) => bidResult(t).fields[letter][field].page;

const cards = () => within(screen.getByTestId("requirements")).getAllByRole("button");

describe("StageResultsWindow, Stage I", () => {
  it("shows item (l) with its verdict, its citation and the highlighted page", async () => {
    const user = userEvent.setup();
    renderStageI("Tenderer_A");

    const l = await waitFor(() => {
      const card = cards().find((c) => c.dataset.letter === "l");
      expect(card).toBeDefined();
      return card;
    });
    expect(l).toHaveTextContent("The signed Non-collusive Tendering Certificate");
    expect(l.dataset.status).toBe("pass");
    await user.click(l);

    const detail = screen.getByTestId("item-detail");
    expect(within(detail).getByText("(l)")).toBeInTheDocument();
    expect(within(detail).getAllByText("Compliant").length).toBeGreaterThan(0);
    // The four checks of the rule set's item (l), with what was read.
    expect(within(detail).getByTestId("check-noncollusive_certificate.tenderer_name")).toHaveTextContent(
      "Tenderer A Chemicals Ltd"
    );
    // The citation: the offer, page 10 (ground_truth.json).
    expect(within(detail).getByRole("button", { name: /offer\.pdf\s*p\.10/ })).toBeInTheDocument();

    const img = await screen.findByAltText("offer.pdf, p.10");
    const src = new URL(img.getAttribute("src"));
    expect(src.pathname).toBe(`/projects/${PID}/documents/${TENDERERS.Tenderer_A.docId}/pages/10/image`);
    expect(src.searchParams.get("sig")).toBeTruthy();
    expect(src.searchParams.has("key")).toBe(false);
    // The highlight is the one the server signed into the citation's image_url,
    // used as given: the UI adds nothing to the link.
    const cited = fixtureCitation("Tenderer_A", "l", "tenderer_name");
    expect(src.searchParams.get("highlight")).toBe("Tenderer A Chemicals Ltd");
    expect(src.searchParams.get("highlight")).toBe(cited.quote);

    // The mock draws the highlight on that image, as the real route does.
    const res = await fetch(src);
    expect(res.status).toBe(200);
    const svg = await res.text();
    expect(svg).toContain('data-highlight="true"');
    expect(svg).toContain("NON-COLLUSIVE TENDERING CERTIFICATE");

    // And the citation's box, scaled by page_size, is drawn over the image.
    const figure = img.closest("figure");
    const overlay = within(figure).getByTestId("page-highlight-box");
    const [x0, y0, x1, y1] = cited.box;
    const [w, h] = cited.page_size;
    expect(parseFloat(overlay.style.left)).toBeCloseTo((x0 / w) * 100, 3);
    expect(parseFloat(overlay.style.top)).toBeCloseTo((y0 / h) * 100, 3);
    expect(parseFloat(overlay.style.width)).toBeCloseTo(((x1 - x0) / w) * 100, 3);
    expect(parseFloat(overlay.style.height)).toBeCloseTo(((y1 - y0) / h) * 100, 3);
  });

  it("sorts problems first: a disqualifying (l) leads for Tenderer_C", async () => {
    renderStageI("Tenderer_C");
    await waitFor(() => expect(cards().length).toBe(3));
    expect(cards().map((c) => [c.dataset.letter, c.dataset.status])).toEqual([
      ["l", "disqualified"],
      ["a", "pass"],
      ["k", "pass"],
    ]);
    // The first item is selected: its verdict says why, and no page is cited.
    const detail = screen.getByTestId("item-detail");
    expect((await within(detail).findAllByText("Disqualifying")).length).toBeGreaterThan(0);
    expect(within(detail).getAllByText(/document is missing; the tender is not considered further/).length).toBeGreaterThan(0);
    expect(within(detail).getByText("No page of the offer was cited for this item.")).toBeInTheDocument();
  });

  it("keeps schedule order when every item passes", async () => {
    renderStageI("Tenderer_D");
    await waitFor(() => expect(cards().length).toBe(3));
    expect(cards().map((c) => c.dataset.letter)).toEqual(["a", "k", "l"]);
  });

  it("runs a check for a tenderer without results, polls the job and shows (l)", async () => {
    const user = userEvent.setup();
    renderStageI("Tenderer_B");
    await user.click(await screen.findByRole("button", { name: /Run check/ }));
    await waitFor(() => expect(cards().find((c) => c.dataset.letter === "l")?.dataset.status).toBe("pass"));
    // Tenderer_B's contact person is illegible: (k) needs review and leads.
    expect(cards()[0].dataset.letter).toBe("k");
    expect(cards()[0].dataset.status).toBe("needs_review");
  });

  it("opens a scanned offer's page without a highlight, a box or an error", async () => {
    const user = userEvent.setup();
    renderStageI("Tenderer_B");
    await user.click(await screen.findByRole("button", { name: /Run check/ }));
    const l = await waitFor(() => {
      const card = cards().find((c) => c.dataset.letter === "l");
      expect(card?.dataset.status).toBe("pass");
      return card;
    });
    await user.click(l);

    // Tenderer_B is scanned: the name was read, but no text layer holds it.
    const img = await screen.findByAltText("offer.pdf, p.13");
    const src = new URL(img.getAttribute("src"));
    expect(src.pathname).toBe(`/projects/${PID}/documents/${TENDERERS.Tenderer_B.docId}/pages/13/image`);
    expect(src.searchParams.get("sig")).toBeTruthy();
    expect(src.searchParams.has("highlight")).toBe(false);
    expect(within(img.closest("figure")).queryByTestId("page-highlight-box")).toBeNull();

    const res = await fetch(src);
    expect(res.status).toBe(200);
    const svg = await res.text();
    expect(svg).not.toContain("data-highlight");
    expect(svg).toContain("NON-COLLUSIVE TENDERING CERTIFICATE");
    expect(screen.queryByText(/invalid or has expired|failed/i)).toBeNull();
  });
});

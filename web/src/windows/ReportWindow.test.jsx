// The Report window on the mock's evaluation and reports (web/mock/fixtures.js).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PID, evaluation } from "../../mock/fixtures.js";
import { server } from "../../mock/node.js";
import ReportWindow from "./ReportWindow.jsx";

async function renderReport() {
  render(<ReportWindow projectId={PID} />);
  await waitFor(() => expect(screen.queryByText(/Loading the evaluation/)).toBeNull());
}

describe("Report window", () => {
  it("shows the two stage conclusions and the recommendation", async () => {
    await renderReport();

    expect(screen.getByText(/did not submit the Manufacturer's Letter of Intent/)).toBeInTheDocument();
    expect(screen.getByText(/met every Stage II requirement/)).toBeInTheDocument();
    expect(screen.getByText(/Tenderer A is recommended/)).toBeInTheDocument();
  });

  it("lists each tenderer with its review and correction count", async () => {
    await renderReport();

    const b = screen.getByRole("row", { name: /Tenderer_B/ });
    expect(within(b).getByText("nasi")).toBeInTheDocument();
    expect(within(b).getByText("1")).toBeInTheDocument();
  });

  it("offers each report and says whether it has been downloaded", async () => {
    await renderReport();

    const priceSummary = screen.getByRole("button", { name: "Price Summary" });
    expect(priceSummary).toBeEnabled();
    // generated_at is null until a report is downloaded once - that is a fact about
    // the report, not a build step the reviewer is waiting on. The price summary in
    // the fixture has been downloaded; the other two have not.
    expect(screen.getAllByText(/not downloaded yet/)).toHaveLength(2);
    const summaryList = screen.getByRole("button", { name: "Summary List" }).closest("li");
    expect(summaryList).toHaveTextContent(/not downloaded yet/);
    expect(priceSummary.closest("li")).toHaveTextContent(/last downloaded/);
  });

  it("names the tenderers whose review still blocks a report, before the click", async () => {
    // The API's 409 review_pending never reaches this window - a report downloads
    // through an <a href> - so the block is derived from the evaluation's own
    // `reviewed_by`, which is what makes the warning visible in time to act on.
    const body = evaluation();
    body.tenderers = body.tenderers.map((t) =>
      t.tenderer === "Tenderer_C" ? { ...t, reviewed_by: null } : t);
    server.use(http.get("*/projects/:pid/evaluation", () => HttpResponse.json(body)));

    await renderReport();

    expect(screen.getByRole("status")).toHaveTextContent(/Still open: Tenderer_C/);
    expect(screen.getByRole("button", { name: "Price Summary" })).toBeDisabled();
  });

  it("says nothing about pending reviews when every one is confirmed", async () => {
    await renderReport();
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("downloading a report", () => {
  // jsdom has no object URLs and no downloads: record what would be saved instead.
  const saved = [];
  function captureDownloads() {
    saved.length = 0;
    URL.createObjectURL = vi.fn(() => "blob:report");
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function () {
      saved.push({ href: this.href, name: this.download });
    });
  }
  afterEach(() => {
    vi.restoreAllMocks();
    delete URL.createObjectURL;
    delete URL.revokeObjectURL;
  });

  it("fetches the file through the API and saves it under the name the API gives", async () => {
    // A plain link cannot send X-API-Key, and the reports route requires it, so the
    // file is fetched like every other call and saved from the Blob.
    captureDownloads();
    const user = userEvent.setup();
    await renderReport();

    await user.click(screen.getByRole("button", { name: "Summary List" }));

    await waitFor(() => expect(saved).toEqual([{ href: "blob:report", name: "summary_list.docx" }]));
    expect(URL.createObjectURL.mock.calls[0][0].size).toBeGreaterThan(0); // the file's bytes, not a link
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says who is still open when the server refuses a report", async () => {
    // The evaluation can be stale: the server's 409 review_pending is the last word.
    captureDownloads();
    server.use(http.get("*/projects/:pid/reports/:name", () => HttpResponse.json(
      { error: { code: "review_pending", message: "the review of Tenderer_D is not confirmed",
                 details: { tenderers: ["Tenderer_D"] } } }, { status: 409 })));
    const user = userEvent.setup();
    await renderReport();

    await user.click(screen.getByRole("button", { name: "Price Summary" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Still open: Tenderer_D/);
    expect(saved).toEqual([]);
  });
});

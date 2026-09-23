// The Report window on the mock's evaluation and reports (web/mock/fixtures.js).
import { render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
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

  it("links each report and says whether it has been downloaded", async () => {
    await renderReport();

    const priceSummary = screen.getByRole("link", { name: "Price Summary" });
    expect(priceSummary).toHaveAttribute("href", expect.stringContaining("/reports/price_summary.docx"));
    expect(priceSummary).toHaveAttribute("download");
    // generated_at is null until a report is downloaded once - that is a fact about
    // the report, not a build step the reviewer is waiting on. The price summary in
    // the fixture has been downloaded; the other two have not.
    expect(screen.getAllByText(/not downloaded yet/)).toHaveLength(2);
    const summaryList = screen.getByRole("link", { name: "Summary List" }).closest("li");
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
  });

  it("says nothing about pending reviews when every one is confirmed", async () => {
    await renderReport();
    expect(screen.queryByRole("status")).toBeNull();
  });
});

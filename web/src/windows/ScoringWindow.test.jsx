// The Scoring window on the mock's price summary (web/mock/fixtures.js): four
// tenderers, A and B conforming, C failing Stage I, D quoting in US$.
import { render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { PID } from "../../mock/fixtures.js";
import { server } from "../../mock/node.js";
import ScoringWindow from "./ScoringWindow.jsx";

const row = (tenderer) => screen.getByRole("row", { name: new RegExp(tenderer) });

async function renderScoring() {
  render(<ScoringWindow projectId={PID} />);
  await waitFor(() => expect(screen.queryByText(/Loading the price summary/)).toBeNull());
}

describe("Scoring window", () => {
  it("ranks every computable offer and names the recommended one", async () => {
    await renderScoring();

    expect(screen.getAllByRole("row")).toHaveLength(5); // header + four tenderers
    expect(within(row("Tenderer_A")).getByText("recommended")).toBeInTheDocument();
    expect(within(row("Tenderer_B")).queryByText("recommended")).toBeNull();
  });

  it("shows a non-conforming offer that ranks above a conforming one", async () => {
    // Tenderer C ranks second, ahead of B and D, but failed Stage I. Hiding
    // it would leave a reviewer unable to see why the cheapest offer is not recommended.
    await renderScoring();

    const c = row("Tenderer_C");
    expect(c.className).toContain("non-conforming");
    expect(within(c).getByText("disqualified")).toBeInTheDocument();
  });

  it("shows a US$ quotation converted, and says so", async () => {
    await renderScoring();

    const d = row("Tenderer_D");
    expect(within(d).getByText(/0\.32 US\$/)).toBeInTheDocument();
    expect(within(d).getByText(/converted at 7\.8/)).toBeInTheDocument();
  });

  it("marks a row a reviewer corrected", async () => {
    await renderScoring();
    expect(within(row("Tenderer_B")).getByText("corrected")).toBeInTheDocument();
  });

  it("states the scheme and where its quantity came from", async () => {
    await renderScoring();
    expect(screen.getByText(/ranked on cost-effectiveness/)).toBeInTheDocument();
    expect(screen.getByText(/Price Schedule Note \(2\)/)).toBeInTheDocument();
  });

  it("explains an unconfirmed rule set rather than showing an empty table", async () => {
    server.use(http.get("*/projects/:pid/price-summary", () =>
      HttpResponse.json({ error: { code: "unconfirmed_ruleset", message: "no confirmed rule set" } }, { status: 409 })));

    await renderScoring();

    expect(screen.getByRole("status")).toHaveTextContent(/Confirm one in the Rules window/);
    expect(screen.queryByRole("table")).toBeNull();
  });
});

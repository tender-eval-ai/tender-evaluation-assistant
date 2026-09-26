// The Scoring window on the mock's price summary (web/mock/fixtures.js): four
// tenderers, A and B conforming, C failing Stage I, D quoting in US$.
import { render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { PID, priceSummary } from "../../mock/fixtures.js";
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

  it("states the currency prices are compared in, and the rates", async () => {
    await renderScoring();
    expect(screen.getByText(/compared in HK\$/)).toBeInTheDocument();
    expect(screen.getByText(/USD at 7\.8/)).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "HK$ equivalent" })).toBeInTheDocument();
  });

  it("leaves an offer it cannot convert unranked, and shows why", async () => {
    const summary = priceSummary();
    const d = summary.rows.find((r) => r.tenderer === "Tenderer_D");
    Object.assign(d, { currency: "C$", unit_price_base: null, estimated_goods_price: null, cost_effectiveness: null, ranking: null,
                       remark: "quoted in C$; no exchange rate from C$ to HK$ is set, so it is not ranked" });
    server.use(http.get("*/projects/:pid/price-summary", () => HttpResponse.json(summary)));

    await renderScoring();

    const row = screen.getByRole("row", { name: /Tenderer_D/ });
    expect(within(row).getByText(/no exchange rate from C\$ to HK\$/)).toBeInTheDocument();
    expect(within(row).getAllByText("—").length).toBeGreaterThanOrEqual(3);
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

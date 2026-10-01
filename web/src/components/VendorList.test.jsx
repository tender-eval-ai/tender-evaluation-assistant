// The bid lists the Stage I and Stage II steps open on: every tenderer with that
// stage's rollup, one click from its own page. The mock's rule set has nothing at
// Stage II (BidResult.stage2 is null), so the Stage II rollups are served here.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import * as fx from "../../mock/fixtures.js";
import { server } from "../../mock/node.js";
import VendorList from "./VendorList.jsx";

const STAGE_II = {
  Tenderer_A: { outcome: "pass", items: { b: "pass", c: "pass" } },
  Tenderer_B: { outcome: "needs_review", items: { b: "pass", c: "needs_review" } },
  Tenderer_C: { outcome: "pass", items: { b: "pass", c: "pass" } },
  Tenderer_D: { outcome: "disqualified", items: { b: "disqualified", c: "pass" } },
};

const withStageII = () =>
  server.use(
    http.get("*/projects/:pid/bids/:tenderer/results", ({ params }) =>
      HttpResponse.json({ ...fx.bidResult(params.tenderer), stage2: STAGE_II[params.tenderer] })
    )
  );

const row = (name) => screen.findByRole("row", { name: new RegExp(name) });
const cells = async (name) => within(await row(name)).getAllByRole("cell").map((c) => c.textContent);

describe("VendorList, Stage II", () => {
  it("lists every tenderer with its Stage II rollup", async () => {
    withStageII();
    render(<VendorList projectId={fx.PID} stage="II" onSelectVendor={() => {}} />);

    const headers = await screen.findAllByRole("columnheader");
    expect(headers.map((h) => h.textContent)).toEqual(["Tenderer", "Rule set", "Pass", "Review", "Fail", "Status"]);
    expect(await cells("Tenderer_A")).toEqual(["Tenderer_A", "v1", "2", "0", "0", "Compliant"]);
    expect(await cells("Tenderer_B")).toEqual(["Tenderer_B", "v1", "1", "1", "0", "Needs human review"]);
    expect(await cells("Tenderer_D")).toEqual(["Tenderer_D", "v1", "1", "0", "1", "Non-compliant"]);
  });

  it("says which tenderer Stage I already put out", async () => {
    withStageII();
    render(<VendorList projectId={fx.PID} stage="II" onSelectVendor={() => {}} />);

    expect(await row("Tenderer_C")).toHaveTextContent("disqualified at Stage I");
    expect(await row("Tenderer_A")).not.toHaveTextContent("disqualified at Stage I");
  });

  it("filters to the non-compliant offers", async () => {
    const user = userEvent.setup();
    withStageII();
    render(<VendorList projectId={fx.PID} stage="II" onSelectVendor={() => {}} />);

    await user.click(await screen.findByRole("button", { name: "non-compliant 1" }));
    const rows = within(screen.getAllByRole("rowgroup")[1]).getAllByRole("row");
    expect(rows.map((r) => r.textContent)).toEqual([expect.stringContaining("Tenderer_D")]);
  });

  it("shows a rule set with nothing at Stage II as such, not as compliant", async () => {
    render(<VendorList projectId={fx.PID} stage="II" onSelectVendor={() => {}} />);

    expect(await row("Tenderer_A")).toHaveTextContent("Nothing at this stage");
    expect(await row("Tenderer_B")).toHaveTextContent("Not checked");
  });

  it("opens the tenderer clicked", async () => {
    const user = userEvent.setup();
    const onSelectVendor = vi.fn();
    withStageII();
    render(<VendorList projectId={fx.PID} stage="II" onSelectVendor={onSelectVendor} />);

    await user.click(await row("Tenderer_D"));
    expect(onSelectVendor).toHaveBeenCalledWith("Tenderer_D");
  });
});

describe("VendorList, Stage I", () => {
  it("keeps its own columns and statuses", async () => {
    render(<VendorList projectId={fx.PID} stage="I" onSelectVendor={() => {}} />);

    const headers = await screen.findAllByRole("columnheader");
    expect(headers.map((h) => h.textContent)).toEqual(["Tenderer", "Rule set", "OK", "Review", "Missing", "Status"]);
    expect(await row("Tenderer_C")).toHaveTextContent("Missing");
    expect(await row("Tenderer_C")).not.toHaveTextContent("disqualified at Stage I");
    expect(await screen.findByRole("button", { name: "missing 1" })).toBeInTheDocument();
  });
});

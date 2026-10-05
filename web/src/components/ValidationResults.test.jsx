import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import VendorItemDetail from "./ValidationResults.jsx";

// Two checks on one field: one passed on its own, the reviewer's decision settled the other.
const decision = { status: "dormant", by: "reviewer-1", reason: "left for the Authority to follow up" };
const verdict = {
  outcome: "pass",
  rule_ids: ["goods.manufacturer_named", "goods.manufacturer_is_maker"],
  evidence: [],
  checks: [
    { field_id: "particulars_of_goods.manufacturer", rule_id: "goods.manufacturer_named", stage: "I", status: "pass", decision },
    { field_id: "particulars_of_goods.manufacturer", rule_id: "goods.manufacturer_is_maker", stage: "I", status: "dormant",
      note: "decided by reviewer-1: left for the Authority to follow up", decision },
  ],
};

describe("a decision on a field with two checks", () => {
  it("shows only on the check it settled", async () => {
    const user = userEvent.setup();
    render(<VendorItemDetail item={{ letter: "d", title: "Particulars of Goods" }} verdict={verdict} values={{}} stageFilter="I" />);
    expect(screen.queryByTestId("decided-particulars_of_goods.manufacturer")).toBeNull();
    await user.click(screen.getByText(/1 not yet required/));
    expect(screen.getAllByTestId("decided-particulars_of_goods.manufacturer")).toHaveLength(1);
  });
});

describe("values no rule checks", () => {
  it("are listed with their page, and checked ones are not", async () => {
    const user = userEvent.setup();
    const seen = [];
    const page = { doc_id: "d", file: "offer.pdf", page: 22, image_url: "/x" };
    const values = {
      document: { value: "Particulars of Goods" },
      manufacturer: { value: "Maker Ltd", page },
      track_record: { value: "5 years", page, confidence: 0.9 },
      shelf_life: { value: null, redacted: true },
    };
    render(<VendorItemDetail item={{ letter: "d", title: "Particulars of Goods" }} verdict={verdict} values={values}
                             stageFilter="I" onViewCitation={(c) => seen.push(c)} />);
    await user.click(screen.getByRole("button", { name: /Other values read · 2/ }));
    expect(screen.getByTestId("other-track_record")).toHaveTextContent("5 years");
    expect(screen.getByTestId("other-shelf_life")).toHaveTextContent("redacted in this copy");
    expect(screen.queryByTestId("other-manufacturer")).toBeNull();
    expect(screen.queryByTestId("other-document")).toBeNull();
    await user.click(within(screen.getByTestId("other-track_record")).getByText("read on offer.pdf, p.22 →"));
    expect(seen).toEqual([page]);
  });
});

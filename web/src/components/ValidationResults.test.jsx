import { render, screen } from "@testing-library/react";
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

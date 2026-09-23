// Corrections and review confirmation in the Stage I window (S4).
//
// Tenderer B's item (k) has a contact_details.contact_person the model could not
// read (confidence 0.31, needs_review). That is the field a reviewer corrects, and
// until it is corrected a confirmation is refused with 409 conflict naming it.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { PID } from "../../mock/fixtures.js";
import StageResultsWindow from "./StageResultsWindow.jsx";

function renderStageI(tenderer = "Tenderer_A") {
  render(<StageResultsWindow projectId={PID} tenderer={tenderer} stage="I" title="Stage I — Completeness" pollMs={5} />);
  return userEvent.setup();
}

const openItem = async (user, letter) => {
  const card = await waitFor(() =>
    within(screen.getByTestId("requirements")).getAllByRole("button").find((b) => b.dataset.letter === letter));
  await user.click(card);
  return card;
};

// Tenderer B has no finished check in the mock's initial state, so the window starts
// one and polls it - the same path a reviewer takes for a tenderer that was added
// after the first run. `pollMs` of 5 makes that a few milliseconds here.
const openAfterCheck = async (user, letter) => {
  await user.click(await screen.findByText("▶ Run check"));
  const card = await waitFor(
    () => within(screen.getByTestId("requirements")).getAllByRole("button").find((b) => b.dataset.letter === letter),
    { timeout: 4000 }
  );
  await user.click(card);
  return card;
};

describe("correcting a field", () => {
  it("requires a reason, as the contract does", async () => {
    const user = renderStageI();
    await openItem(user, "a");

    await user.click(within(screen.getByTestId("check-offer_to_be_bound.document")).getByText("correct this field"));
    const form = screen.getByRole("form", { name: /Correct offer_to_be_bound.document/ });
    await user.selectOptions(within(form).getByLabelText("Document"), "absent");
    await user.click(within(form).getByRole("button", { name: "Save correction" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("A reason is required.");
  });

  it("refuses a correction that changes nothing", async () => {
    const user = renderStageI();
    await openItem(user, "a");

    await user.click(within(screen.getByTestId("check-offer_to_be_bound.document")).getByText("correct this field"));
    const form = screen.getByRole("form", { name: /Correct offer_to_be_bound.document/ });
    await user.type(within(form).getByLabelText("Reason"), "typo");
    await user.click(within(form).getByRole("button", { name: "Save correction" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Change a value/);
  });

  it("keeps the model's value beside the person's, with who and why", async () => {
    const user = renderStageI("Tenderer_B");
    await openAfterCheck(user, "k");

    const row = screen.getByTestId("check-contact_details.contact_person");
    await user.click(within(row).getByText("correct this field"));
    const form = screen.getByRole("form", { name: /contact_person/ });
    await user.type(within(form).getByLabelText("Value"), "Pat Example");
    await user.type(within(form).getByLabelText("Reason"), "legible on the scan at 200%");
    await user.click(within(form).getByRole("button", { name: "Save correction" }));

    const corrected = await screen.findByTestId("corrected-contact_details.contact_person");
    expect(corrected).toHaveTextContent("legible on the scan at 200%");
    expect(corrected).toHaveTextContent("anonymous");
  });
});

describe("confirming a review", () => {
  it("refuses while a field still needs review, and names it", async () => {
    const user = renderStageI("Tenderer_B");
    await openAfterCheck(user, "k");

    await user.click(screen.getByText("confirm this review"));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Still needing review/);
  });

  it("confirms once nothing needs review, and says who", async () => {
    const user = renderStageI("Tenderer_A");
    await openItem(user, "a");

    await user.click(screen.getByText("confirm this review"));

    await waitFor(() =>
      expect(screen.getByTestId("review-confirm")).toHaveTextContent(/review confirmed by anonymous/));
  });
});

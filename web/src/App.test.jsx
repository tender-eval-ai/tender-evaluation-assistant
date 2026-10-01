// Moving between the Stage I and Stage II steps: both open on the list of
// tenderers, and a tenderer picked on one stays picked on the other.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import App from "./App.jsx";

const step = async (name) => {
  const button = await screen.findByRole("button", { name });
  // Every step past the rules waits for the confirmed rule set to load.
  await waitFor(() => expect(button).toBeEnabled());
  return button;
};

describe("the Stage I and Stage II steps", () => {
  afterEach(() => window.localStorage.clear());

  it("Stage II lists every tenderer and opens the one picked", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /syn-2026-001/i }));
    await user.click(await step(/STAGE II COMPLIANCE/));

    for (const t of ["Tenderer_A", "Tenderer_B", "Tenderer_C", "Tenderer_D"]) {
      expect(await screen.findByRole("row", { name: new RegExp(t) })).toBeInTheDocument();
    }
    await user.click(screen.getByRole("row", { name: /Tenderer_C/ }));
    expect(await screen.findByText(/Stage II — Compliance · Tenderer_C/)).toBeInTheDocument();

    // The pick carries over to Stage I, and back to the list from there.
    await user.click(await step(/STAGE I COMPLETENESS/));
    expect(await screen.findByText(/Stage I — Completeness · Tenderer_C/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "← All tenderers" }));
    expect(await screen.findByRole("row", { name: /Tenderer_D/ })).toBeInTheDocument();
  });
});

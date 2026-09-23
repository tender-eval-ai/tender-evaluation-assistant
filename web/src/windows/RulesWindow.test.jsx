// The Rules window on the mock's rule sets (web/mock/rulesetStore.js): v1
// confirmed, v2 a draft in which item (c) needs input and gap Supp:13:(d) has
// no reason. The acting user starts as "anonymous"; chenyu built the draft.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { PID } from "../../mock/fixtures.js";
import { setActingUser } from "../api.js";
import RulesWindow from "./RulesWindow.jsx";

afterEach(() => setActingUser(""));

const card = (letter) => within(screen.getByTestId("rule-items")).queryAllByRole("button").find((b) => b.dataset.letter === letter);

async function renderRules() {
  const user = userEvent.setup();
  render(<RulesWindow projectId={PID} />);
  await waitFor(() => expect(card("c")).toBeDefined());
  return user;
}

async function openItem(user, letter) {
  await user.click(card(letter));
  const detail = screen.getByTestId("rule-item-detail");
  await waitFor(() => expect(within(detail).getByText(`(${letter})`)).toBeInTheDocument());
  return detail;
}

describe("RulesWindow", () => {
  it("lists the draft's items by Part with their status", async () => {
    await renderRules();
    expect(screen.getByRole("combobox", { name: "Rule set version" })).toHaveValue("2");
    expect(card("c").dataset.status).toBe("needs_input");
    expect(card("k").dataset.status).toBe("edited");
    expect(card("a").dataset.status).toBe("novel");
  });

  it("an edit needs a reason, and the corrected slot keeps the model's value beside it", async () => {
    const user = await renderRules();
    const detail = await openItem(user, "c");
    const slot = within(detail).getByTestId("slot-estimated_quantity");
    expect(within(slot).queryByTestId("model-value-estimated_quantity")).toBeNull();

    await user.click(within(slot).getByRole("button", { name: "edit slot estimated_quantity" }));
    const form = within(slot).getByRole("form", { name: "Correct slot estimated_quantity" });
    const value = within(form).getByRole("textbox", { name: /New value/ });
    await user.clear(value);
    await user.type(value, "1250");
    const save = within(form).getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    expect(within(form).getByText("A reason is required before the change can be saved.")).toBeInTheDocument();

    await user.type(within(form).getByRole("textbox", { name: /Reason/ }), "Addendum 1 raised the estimate");
    expect(save).toBeEnabled();
    await user.click(save);

    const corrected = await screen.findByTestId("model-value-estimated_quantity");
    expect(corrected).toHaveTextContent("Model’s value: 1200");
    const after = screen.getByTestId("slot-estimated_quantity");
    expect(after).toHaveTextContent("1250");
    expect(after).toHaveTextContent("manual · unverified");
    expect(after).toHaveTextContent(/Corrected by anonymous .*“Addendum 1 raised the estimate”/);
    expect(card("c").dataset.status).toBe("edited");
  });

  it("confirm is refused (409) while an item needs input and a gap has no reason", async () => {
    const user = await renderRules();
    await user.click(screen.getByRole("button", { name: "✓ Confirm draft v2" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Draft v2 cannot be confirmed yet:");
    expect(alert).toHaveTextContent("item (c) needs input");
    expect(alert).toHaveTextContent("gap Supp:13:(d) has no reason");

    // The blocker leads to the item.
    await user.click(within(alert).getByRole("button", { name: "item (c) needs input" }));
    expect(within(screen.getByTestId("rule-item-detail")).getByText("(c)")).toBeInTheDocument();
  });

  it("the last editor cannot confirm (403 self_approval); another person can", async () => {
    const user = await renderRules();
    // Fill (c)'s empty slot and give the open gap a reason, as anonymous.
    const detail = await openItem(user, "c");
    const slot = within(detail).getByTestId("slot-delivery_period_days");
    await user.click(within(slot).getByRole("button", { name: "edit slot delivery_period_days" }));
    await user.type(within(slot).getByRole("textbox", { name: /New value/ }), "30");
    await user.type(within(slot).getByRole("textbox", { name: /Reason/ }), "Clause SCC 5.2 states 30 days");
    await user.click(within(slot).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(card("c").dataset.status).toBe("edited"));

    await user.click(screen.getByRole("tab", { name: /Gaps/ }));
    const gap = screen.getByTestId("gap-Supp:13:(d)");
    await user.click(within(gap).getByRole("button", { name: "give a reason for gap Supp:13:(d)" }));
    await user.type(within(gap).getByRole("textbox", { name: /Reason/ }), "The sample is handled at the plant trial");
    await user.click(within(gap).getByRole("button", { name: "Save the reason" }));
    await waitFor(() => expect(screen.getByTestId("gap-Supp:13:(d)")).toHaveTextContent("No rule because: The sample is handled at the plant trial"));
    expect(screen.getByText("Ready: a person other than the last editor confirms it.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "✓ Confirm draft v2" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("You made the last change to draft v2, so you cannot confirm it.");
    expect(alert).toHaveTextContent("anonymous last edited draft v2; another person must confirm it");

    const acting = screen.getByRole("textbox", { name: "Acting user" });
    await user.clear(acting);
    await user.type(acting, "chenyu");
    expect(screen.queryByRole("alert")).toBeNull();
    await user.click(screen.getByRole("button", { name: "✓ Confirm draft v2" }));
    expect(await screen.findByText(/✓ v2 confirmed by chenyu/)).toBeInTheDocument();
  });

  it("shows the diff between two versions, with the edit record and the values before and after", async () => {
    const user = await renderRules();
    await user.click(screen.getByRole("tab", { name: "Changes" }));
    const diff = screen.getByTestId("diff");
    expect(within(diff).getByRole("combobox", { name: "From version" })).toHaveValue("1");
    expect(within(diff).getByRole("combobox", { name: "To version" })).toHaveValue("2");

    expect(await within(diff).findByTestId("diff-added-c")).toHaveTextContent("The Price Schedule, completed for the estimated quantity");
    const k = within(diff).getByTestId("diff-changed-k");
    expect(k).toHaveTextContent(/by chenyu .*“Handwritten names are accepted on the synthetic Contact Details form”/);
    const row = within(k).getByText("rules.contact_details.contact_person").closest("tr");
    const [, before, afterCell] = within(row).getAllByRole("cell");
    expect(before).not.toHaveTextContent("printed or handwritten");
    expect(afterCell).toHaveTextContent("The contact person may be printed or handwritten");
    expect(within(k).getByText("status").closest("tr")).toHaveTextContent(/status\s*novel\s*edited/);

    await user.selectOptions(within(diff).getByRole("combobox", { name: "From version" }), "2");
    expect(await within(diff).findByText("No differences between v2 and v2.")).toBeInTheDocument();
  });

  it("deletes an item only with a reason, and the diff records it as removed", async () => {
    const user = await renderRules();
    const detail = await openItem(user, "k");
    await user.click(within(detail).getByRole("button", { name: "Delete item (k)" }));
    const form = within(detail).getByRole("form", { name: "Delete item (k)" });
    const remove = within(form).getByRole("button", { name: "Delete the item" });
    expect(remove).toBeDisabled();
    await user.type(within(form).getByRole("textbox", { name: /Reason/ }), "Contact details are asked for in (a)");
    await user.click(remove);

    await waitFor(() => expect(card("k")).toBeUndefined());
    await user.click(screen.getByRole("tab", { name: "Changes" }));
    expect(await screen.findByTestId("diff-removed-k")).toHaveTextContent("The Appendix to the Terms of Tender - Contact Details");
  });

  it("the JSON editor lists the 422 validation errors of a bad draft", async () => {
    const user = await renderRules();
    await user.click(screen.getByRole("tab", { name: "JSON" }));
    const editor = screen.getByRole("textbox", { name: "Rule set JSON" });
    const draft = JSON.parse(editor.value);
    draft.items[0].part = "Z";
    delete draft.items[1].title;
    fireEvent.change(editor, { target: { value: JSON.stringify(draft, null, 2) } });
    await user.click(screen.getByRole("button", { name: "Save the draft" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("the rule set does not validate");
    expect(alert).toHaveTextContent("items[0].part: Input should be 'A', 'B', 'C'");
    expect(alert).toHaveTextContent("items[1].title: Field required");
  });

  it("adds an item from a clause; the clause becomes its citation", async () => {
    const user = await renderRules();
    await user.click(screen.getByRole("button", { name: "+ add an item from a clause" }));
    const form = screen.getByRole("form", { name: "Add an item from a clause" });
    await user.type(within(form).getByRole("textbox", { name: "Title" }), "Product sample");
    await user.selectOptions(within(form).getByRole("combobox", { name: "Document" }), "04 Terms of Tender (Supplement).pdf");
    const page = within(form).getByRole("spinbutton", { name: "Page" });
    await user.clear(page);
    await user.type(page, "5");
    await user.type(within(form).getByRole("textbox", { name: /Clause text/ }), "The Tenderer shall submit one sample bag");
    await user.type(within(form).getByRole("textbox", { name: /Reason/ }), "Gap Supp:13:(d) needs a rule");
    await user.click(within(form).getByRole("button", { name: "Add the item" }));

    await waitFor(() => expect(card("x1")).toBeDefined());
    const detail = screen.getByTestId("rule-item-detail");
    expect(within(detail).getByText("Product sample")).toBeInTheDocument();
    expect(within(detail).getByRole("button", { name: /The Tenderer shall submit one sample bag\s*p\.5/ })).toBeInTheDocument();
    expect(within(detail).getByTestId("rule-product_sample.submitted")).toHaveTextContent("blank → needs_review");
  });
});

describe("re-evaluating against a confirmed version", () => {
  it("is offered on a confirmed version and not on a draft", async () => {
    const user = await renderRules();
    // v2 is the draft, and the window opens on it.
    expect(screen.queryByText(/re-evaluate every tenderer/)).toBeNull();

    await user.selectOptions(screen.getByLabelText("Rule set version"), "1");

    expect(await screen.findByText(/re-evaluate every tenderer against v1/)).toBeInTheDocument();
  });

  it("says what re-evaluating costs a reviewer", async () => {
    // A result whose verdict changes loses its review confirmation, so a reviewer
    // is told before it happens rather than discovering it afterwards.
    const user = await renderRules();
    await user.selectOptions(screen.getByLabelText("Rule set version"), "1");
    await user.click(screen.getByText(/re-evaluate every tenderer against v1/));

    expect(await screen.findByText(/loses its review confirmation/)).toBeInTheDocument();
  });
});

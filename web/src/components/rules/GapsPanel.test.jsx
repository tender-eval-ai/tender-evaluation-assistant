// One reason for every open gap in one save: a synthetic tender left 72 (2026-09-30).
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import GapsPanel from "./GapsPanel.jsx";

const gaps = [
  { node_id: "04:9.1", text: "The Authority Representative shall deliver…", reason: null },
  { node_id: "04:9.2", text: "The Authority shall keep a record…", reason: null },
  { node_id: "04:9.3", text: "The store keeper shall…", reason: "the Authority's own duty" },
];

describe("gaps", () => {
  it("take one reason for all the open ones", async () => {
    const onSaveReasons = vi.fn(() => Promise.resolve());
    render(<GapsPanel gaps={gaps} editable onSaveReason={vi.fn()} onSaveReasons={onSaveReasons} />);
    const user = userEvent.setup();
    const all = screen.getByTestId("gaps-all");
    await user.click(within(all).getByRole("button", { name: "give one reason to all 2 open gaps" }));
    await user.type(within(all).getByRole("textbox", { name: /Reason/ }), "obligations on the Authority, not the tenderer");
    await user.click(within(all).getByRole("button", { name: "Save the reason for all 2" }));
    expect(onSaveReasons).toHaveBeenCalledWith(["04:9.1", "04:9.2"], "obligations on the Authority, not the tenderer");
  });

  it("aren't offered in bulk when one or none is open, or the draft can't be edited", () => {
    const { rerender } = render(<GapsPanel gaps={gaps.slice(1)} editable onSaveReason={vi.fn()} onSaveReasons={vi.fn()} />);
    expect(screen.queryByTestId("gaps-all")).toBeNull();
    rerender(<GapsPanel gaps={gaps} editable={false} onSaveReason={vi.fn()} onSaveReasons={vi.fn()} />);
    expect(screen.queryByTestId("gaps-all")).toBeNull();
  });
});

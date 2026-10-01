import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as fx from "../../mock/fixtures.js";
import { server } from "../../mock/node.js";
import TopNav from "../components/TopNav.jsx";
import { lastStep, rememberStep } from "../projectStage.js";
import ProjectPicker from "./ProjectPicker.jsx";

const unconfirmed = () =>
  HttpResponse.json({ error: { code: "unconfirmed_ruleset", message: "no confirmed rule set" } }, { status: 409 });

describe("the stage badge on a project card", () => {
  afterEach(() => window.localStorage.clear());

  it("is a green tick once every tenderer is checked and reviewed", async () => {
    render(<ProjectPicker onSelect={() => {}} />);
    const badge = await screen.findByTestId("project-stage");
    expect(badge).toHaveTextContent("✓");
    expect(badge).toHaveAttribute("title", expect.stringMatching(/^Finished/));
  });

  it("shows the step this browser last had open while the project is unfinished", async () => {
    server.use(http.get("*/projects/:pid/evaluation", unconfirmed));
    rememberStep(fx.PID, "scoring");
    render(<ProjectPicker onSelect={() => {}} />);
    const badge = await screen.findByTestId("project-stage");
    expect(badge).toHaveTextContent("s4");
    expect(badge).toHaveAttribute("title", "In progress: last open at step 4, Scoring");
  });

  it("falls back to the rules for a project with no confirmed rule set and no remembered step", async () => {
    server.use(http.get("*/projects/:pid/evaluation", unconfirmed));
    render(<ProjectPicker onSelect={() => {}} />);
    expect(await screen.findByTestId("project-stage")).toHaveTextContent("s1");
  });

  it("ignores a stored step it doesn't know", () => {
    window.localStorage.setItem(`tender-eval:last-step:${fx.PID}`, "elsewhere");
    expect(lastStep(fx.PID)).toBeNull();
  });
});

describe("the top bar", () => {
  it("has a Change project button that goes back to the project list", async () => {
    const onChangeProject = vi.fn();
    render(<TopNav tenderName="Showcase" onChangeProject={onChangeProject} user="anonymous" />);
    await userEvent.setup().click(within(screen.getByRole("banner")).getByRole("button", { name: /Change project/ }));
    expect(onChangeProject).toHaveBeenCalledOnce();
  });
});

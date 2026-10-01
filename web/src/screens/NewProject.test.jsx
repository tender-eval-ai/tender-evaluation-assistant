// The front door (#132): a new project from a prepared case, drafted and opened; and a
// hosted demo that says why it takes no uploads and where to run it on real documents.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import * as fx from "../../mock/fixtures.js";
import { server } from "../../mock/node.js";
import ProjectPicker from "./ProjectPicker.jsx";

// jsdom's File isn't the Blob Node's fetch sends, so the uploads are stubbed here;
// contract.test.js sends real multipart bodies to the mock's upload routes.
const uploads = vi.hoisted(() => ({ tender: [], bids: [] }));
vi.mock("../api.js", async (original) => ({
  ...(await original()),
  uploadTender: vi.fn(async (pid, files) => { uploads.tender.push(files.map((f) => f.name)); return { saved: [] }; }),
  uploadBid: vi.fn(async (pid, t, files) => { uploads.bids.push([t, files.map((f) => f.name)]); return { saved: [] }; }),
}));

const HOSTED = { hosted_demo: true, data_classes: ["synthetic"], uploads: false,
                 source_url: "https://github.com/tender-eval-ai/tender-evaluation-assistant" };

describe("a new project", () => {
  it("starts from a prepared case, drafts the rules and opens the project", async () => {
    const onSelect = vi.fn();
    render(<ProjectPicker onSelect={onSelect} pollMs={5} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "+ New project" }));

    const card = await screen.findByTestId("case-synthetic_tender");
    expect(card).toHaveTextContent(fx.CASE_CARD.title);
    expect(card).toHaveTextContent("Tenderer C leaves out the Non-collusive Tendering Certificate");
    expect(card).toHaveAttribute("aria-checked", "true");

    await user.click(screen.getByRole("button", { name: "Create and draft the rules" }));
    await waitFor(() => expect(onSelect).toHaveBeenCalledTimes(1), { timeout: 4000 });
    expect(onSelect.mock.calls[0][0]).toMatch(/^small-tender-four-offers-/);
  });

  it("takes the tender's and the offers' own PDFs where uploads are allowed", async () => {
    const onSelect = vi.fn();
    render(<ProjectPicker onSelect={onSelect} pollMs={5} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "+ New project" }));
    await user.click(await screen.findByLabelText("my own PDFs"));
    await user.type(screen.getByLabelText("Name"), "Flocculants 2027");
    await user.click(screen.getByRole("button", { name: "Create and draft the rules" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Add the tender's PDFs.");

    const pdf = (name) => new File(["%PDF-1.4"], name, { type: "application/pdf" });
    await user.upload(screen.getByLabelText("Tender documents"), [pdf("terms.pdf")]);
    await user.type(screen.getByLabelText("Tenderer 1 name"), "Tenderer_X");
    await user.upload(screen.getByLabelText("Tenderer 1 offer"), [pdf("offer.pdf")]);
    expect(screen.getByLabelText("Data class")).toHaveValue("confidential");
    await user.click(screen.getByRole("button", { name: "Create and draft the rules" }));
    await waitFor(() => expect(onSelect).toHaveBeenCalledTimes(1), { timeout: 4000 });
    expect(onSelect.mock.calls[0][0]).toMatch(/^flocculants-2027-/);
    expect(uploads.tender).toEqual([["terms.pdf"]]);
    expect(uploads.bids).toEqual([["Tenderer_X", ["offer.pdf"]]]);
  });
});

describe("a hosted demo", () => {
  it("says it runs synthetic cases only, and where to run it on real documents", async () => {
    server.use(http.get("*/settings", () => HttpResponse.json(HOSTED)));
    render(<ProjectPicker onSelect={() => {}} />);
    const user = userEvent.setup();
    const banner = await screen.findByTestId("demo-banner");
    expect(within(banner).getByRole("link")).toHaveAttribute("href", `${HOSTED.source_url}#quickstart`);

    await user.click(await screen.findByRole("button", { name: "+ New project" }));
    expect(await screen.findByLabelText("my own PDFs")).toBeDisabled();
    expect(screen.getByTestId("uploads-off")).toHaveTextContent("synthetic cases only");
  });
});

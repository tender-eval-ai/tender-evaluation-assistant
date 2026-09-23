// The S4 review flow end to end, in a real browser, on the MSW mock: rules, run a
// check, correct a field a reviewer can see is wrong, watch the verdict change,
// confirm the review, then the Scoring and Report windows.
//
// Against the real API the same steps hold - the mock answers the contract and the
// contract test proves it - which is what makes this worth writing here.
import { expect, test } from "@playwright/test";

const openProject = async (page) => {
  await page.goto("/");
  await page.getByRole("button", { name: /syn-2026-001/i }).click();
};

const stage = (page, name) => page.getByRole("button", { name: new RegExp(name) });

test("a reviewer corrects a field, the verdict changes, and the review confirms", async ({ page }) => {
  await openProject(page);
  await stage(page, "STAGE I COMPLETENESS").click();

  // Tenderer B has no finished check yet - the path a reviewer takes for a tenderer
  // added after the first run.
  await page.getByRole("cell", { name: "Tenderer_B" }).click();
  await page.getByText("▶ Run check").click();

  const k = page.locator('[data-letter="k"]');
  await expect(k).toBeVisible({ timeout: 30_000 });
  await k.click();

  // The model could not read the contact person on B's scan, so it needs review and
  // a confirmation is refused until someone settles it.
  // The badge shows the label, not the wire value ("needs_review").
  const field = page.getByTestId("check-contact_details.contact_person");
  await expect(field).toContainText("Needs human review");

  await page.getByText("confirm this review").click();
  await expect(page.getByRole("alert")).toContainText("Still needing review");

  await field.getByText("correct this field").click();
  const form = page.getByRole("form", { name: /contact_person/ });
  await form.getByLabel("Value").fill("Pat Example");
  await form.getByLabel("Reason").fill("legible on the scan at 200%");
  await form.getByRole("button", { name: "Save correction" }).click();

  // The model's value stays beside the person's, with who and why.
  const corrected = page.getByTestId("corrected-contact_details.contact_person");
  await expect(corrected).toContainText("legible on the scan at 200%");
  await expect(field).not.toContainText("Needs human review");

  await page.getByText("confirm this review").click();
  await expect(page.getByTestId("review-confirm")).toContainText("review confirmed by");
});

test("Scoring ranks every offer and names the recommended one", async ({ page }) => {
  await openProject(page);
  await stage(page, "SCORING").click();

  const recommended = page.getByRole("row", { name: /Tenderer_A/ });
  await expect(recommended).toContainText("recommended");

  // A non-conforming offer that outranks a conforming one stays visible: hiding it
  // leaves a reviewer unable to see why the cheapest offer is not the recommended one.
  await expect(page.getByRole("row", { name: /Tenderer_C/ })).toContainText("disqualified");
  // A US$ quotation is shown as quoted and as converted, and says so.
  await expect(page.getByRole("row", { name: /Tenderer_D/ })).toContainText("converted at 7.8");
});

test("Report shows the conclusions and downloads a report as a file", async ({ page }) => {
  await openProject(page);
  await stage(page, "REPORT").click();

  await expect(page.getByText(/Tenderer A is recommended/)).toBeVisible();
  for (const name of ["Price Summary", "Summary List", "Detailed Evaluation Record"]) {
    await expect(page.getByRole("button", { name })).toBeEnabled();
  }
  // Fetched with the API key and saved from the Blob - a plain link cannot send the
  // key - so the browser's own download is what proves it works.
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Price Summary" }).click();
  expect((await download).suggestedFilename()).toBe("price_summary.docx");
});

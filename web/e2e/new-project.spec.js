// The front door (#132) in a real browser, on the MSW mock: a new project from the
// prepared synthetic case, its rules drafted, and the Rules window open on the draft.
import { expect, test } from "@playwright/test";

test("a visitor starts a project from a prepared case and lands on the drafted rules", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "+ New project" }).click();

  const card = page.getByTestId("case-synthetic_tender");
  await expect(card).toContainText("Small tender, four offers");
  await expect(card).toContainText("Tenderer C leaves out the Non-collusive Tendering Certificate");

  await page.getByRole("button", { name: "Create and draft the rules" }).click();

  // The Rules window, on the new project's draft.
  await expect(page.getByRole("button", { name: /RULES/ }).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Small tender, four offers").first()).toBeVisible();
  await expect(page.locator('[data-letter="l"]').first()).toBeVisible();
});

// The S2 stop point in a real browser: item (l) of the synthetic tender shows
// in the Stage I window with its page highlighted. A stub until Playwright is
// installed (it is not a dependency yet, to keep `npm ci` light):
//
//   npm i -D @playwright/test && npx playwright install chromium
//   npm run dev &            # on web/mock/, or VITE_API_BASE=... for the real API
//   npx playwright test e2e/
//
// Against the real API the same steps hold: that is the S2 check.
import { expect, test } from "@playwright/test";

const BASE = process.env.WEB_URL ?? "http://localhost:5173";

test("item (l) shows in Stage I with its page highlighted", async ({ page }) => {
  await page.goto(BASE);
  await page.getByRole("button", { name: /syn-2026-001/i }).click();
  await page.getByRole("button", { name: /STAGE I COMPLETENESS/ }).click();
  await page.getByRole("cell", { name: "Tenderer_A" }).click();

  const l = page.locator('[data-letter="l"]');
  await expect(l).toContainText("Non-collusive Tendering Certificate");
  await l.click();

  const img = page.getByAltText("offer.pdf, p.10");
  await expect(img).toBeVisible();
  const src = new URL(await img.getAttribute("src"));
  expect(src.searchParams.get("highlight")).toBeTruthy();
});

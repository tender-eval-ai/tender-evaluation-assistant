import { defineConfig, devices } from "@playwright/test";

// The review flow in a real browser, against the MSW mock: no backend, no database,
// no secrets - the same conditions the Vitest suite runs under, which is what lets
// this run in CI at all.
//
// `npm run dev` serves the app on the mock (no VITE_API_BASE means USE_MOCK). Point
// WEB_URL at a running instance to use an already-started server, or set
// VITE_API_BASE when the dev server starts to run the same flow against the real API -
// the steps are the same, which is the point of writing them against the contract.
const PORT = 5173;
const URL = process.env.WEB_URL ?? `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  // A flow test is a sequence; a retry hides a real ordering bug, so there are none
  // locally. CI retries once, because a cold dev server is a genuine flake source.
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  use: {
    baseURL: URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: process.env.WEB_URL
    ? undefined
    : {
        command: `npm run dev -- --port ${PORT} --strictPort`,
        url: URL,
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
      },
});

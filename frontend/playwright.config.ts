import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "dashboard.spec.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  expect: { timeout: 10000 },
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 960 },
  },
  reporter: [["list"], ["json", { outputFile: "test-results/results.json" }]],
  webServer: [
    {
      command: "node tests/transport-fixture.mjs",
      url: "http://127.0.0.1:8067/api/v1/health/live",
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --mode e2e --port 4173",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: false,
    },
  ],
});

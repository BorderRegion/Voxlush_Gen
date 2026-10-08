import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "real-backend.spec.ts",
  workers: 1,
  timeout: 120000,
  expect: { timeout: 90000 },
  use: {
    baseURL: "http://127.0.0.1:8068",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 960 },
  },
  reporter: [
    ["list"],
    ["json", { outputFile: "test-results/real-results.json" }],
  ],
  webServer: {
    command: "../.venv/bin/python tests/real-fixture.py",
    url: "http://127.0.0.1:8068/api/v1/health/live",
    reuseExistingServer: false,
    timeout: 120000,
  },
});

import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  retries: 0,
  reporter: "line",
  timeout: 30_000,
  use: {
    baseURL,
    locale: "en-US",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "edge",
      use: { ...devices["Desktop Edge"], channel: "msedge" },
    },
  ],
});

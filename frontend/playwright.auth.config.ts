import { defineConfig, devices } from "@playwright/test";

const frontendPort = process.env.E2E_AUTH_FRONTEND_PORT ?? "3001";
const frontendURL =
  process.env.PLAYWRIGHT_AUTH_BASE_URL ?? `http://localhost:${frontendPort}`;
const skipWebServer = process.env.PLAYWRIGHT_SKIP_WEB_SERVER === "1";

/**
 * Auth-enabled E2E coverage for the login and setup pages. The default config
 * runs with auth disabled so workspace tests can skip a real session; that
 * would SSR-redirect these pages before page.route() can exercise recovery.
 */
export default defineConfig({
  testDir: "./tests/e2e-auth",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "html",
  timeout: 30_000,

  use: {
    baseURL: frontendURL,
    locale: "en-US",
    trace: "on-first-retry",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: skipWebServer
    ? undefined
    : {
        command: `pnpm build && pnpm exec next start -p ${frontendPort}`,
        url: frontendURL,
        reuseExistingServer: !process.env.CI,
        timeout: 240_000,
        env: {
          SKIP_ENV_VALIDATION: "1",
          DEER_FLOW_AUTH_DISABLED: "0",
          DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: "http://127.0.0.1:65535",
          DEER_FLOW_TRUSTED_ORIGINS: frontendURL,
        },
      },
});

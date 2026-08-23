import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";
// The marketing landing page is only rendered when NEXT_PUBLIC_STATIC_WEBSITE_ONLY=true.
// It is served by a dedicated webServer + project (see below) so the rest of the
// suite keeps exercising the full deployment, where `/` now redirects into the
// app instead of showing the official website (#3909).
const staticBaseURL =
  process.env.PLAYWRIGHT_STATIC_BASE_URL ?? "http://localhost:3100";
const skipWebServer = process.env.PLAYWRIGHT_SKIP_WEB_SERVER === "1";

const webServers = skipWebServer
  ? undefined
  : [
      // Full deployment: `/` redirects into the app. DEER_FLOW_AUTH_DISABLED=1
      // makes getServerSideUser() resolve to "authenticated", so `/` -> /workspace.
      {
        command:
          "./node_modules/.bin/next build && ./node_modules/.bin/next start",
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        env: {
          SKIP_ENV_VALIDATION: "1",
          DEER_FLOW_AUTH_DISABLED: "1",
        },
      },
      // Static marketing website: NEXT_PUBLIC_STATIC_WEBSITE_ONLY=true renders
      // the landing at `/`. `next dev` (not `next build`) reads the flag at
      // runtime, and a separate distDir avoids clobbering the full build's `.next`.
      {
        command: "./node_modules/.bin/next dev -p 3100",
        url: staticBaseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        env: {
          SKIP_ENV_VALIDATION: "1",
          DEER_FLOW_AUTH_DISABLED: "1",
          NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "true",
          PLAYWRIGHT_STATIC_WEBSITE: "1",
        },
      },
    ];

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "html",
  timeout: 30_000,

  use: {
    baseURL,
    locale: "en-US",
    trace: "on-first-retry",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      // The marketing landing is exercised by the static-website project below.
      exclude: ["**/landing.spec.ts"],
    },
    {
      name: "static-website",
      use: { ...devices["Desktop Chrome"], baseURL: staticBaseURL },
      include: ["**/landing.spec.ts"],
    },
  ],

  webServer: webServers,
});

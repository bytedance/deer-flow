import { defineConfig } from "@playwright/test";

// Isolated, mocked connector smoke test. No authenticated Gateway is required.
const externalURL = process.env.PLAYWRIGHT_ENTERPRISE_BASE_URL;
export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: ["enterprise.spec.ts", "enterprise-mail.spec.ts"],
  timeout: 45_000,
  reporter: "list",
  use: {
    baseURL: externalURL ?? "http://127.0.0.1:3101",
    locale: "en-US",
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? {
          executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
          args: ["--no-sandbox"],
        }
      : undefined,
  },
  webServer: externalURL
    ? undefined
    : {
        command:
          process.env.PLAYWRIGHT_ENTERPRISE_DEV === "1"
            ? "python ../scripts/pnpm.py exec next dev --webpack --hostname 127.0.0.1 --port 3101"
            : "python ../scripts/pnpm.py exec next start --hostname 127.0.0.1 --port 3101",
        url: "http://127.0.0.1:3101/login",
        reuseExistingServer: false,
        timeout: 60_000,
        env: {
          DEER_FLOW_AUTH_DISABLED: "1",
          SKIP_ENV_VALIDATION: "1",
          NODE_ENV:
            process.env.PLAYWRIGHT_ENTERPRISE_DEV === "1"
              ? "development"
              : "production",
        },
      },
});

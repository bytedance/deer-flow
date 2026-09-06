import { defineConfig, devices } from "@playwright/test";

/**
 * RECORD-through-browser config (Plan A): drive the REAL frontend against a
 * REAL-model gateway and capture every model call so the fixture's inputs match
 * exactly what the frontend produces. Manual, needs OPENAI_API_KEY/OPENAI_API_BASE
 * + DEERFLOW_RECORD_OUT in the environment — never run in CI.
 *
 * Not committed as a test run; `tests/e2e-record/` holds the driver spec.
 */
export default defineConfig({
  testDir: "./tests/e2e-record",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  timeout: 200_000,
  use: { baseURL: "http://localhost:3000", trace: "off" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "uv run python scripts/record_gateway.py",
      cwd: "../backend",
      url: "http://localhost:8012/health",
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        RECORD_PORT: "8012",
        RECORD_MODEL: process.env.RECORD_MODEL ?? "gpt-5.5",
        // Forwarded from the invoking shell; never hardcoded. Passed through only
        // when actually set, so record_gateway.py raises a clear "missing env"
        // error instead of receiving "" (which would write to Path("")).
        ...(process.env.DEERFLOW_RECORD_OUT
          ? { DEERFLOW_RECORD_OUT: process.env.DEERFLOW_RECORD_OUT }
          : {}),
        ...(process.env.OPENAI_API_KEY
          ? { OPENAI_API_KEY: process.env.OPENAI_API_KEY }
          : {}),
        ...(process.env.OPENAI_API_BASE
          ? { OPENAI_API_BASE: process.env.OPENAI_API_BASE }
          : {}),
      },
    },
    {
      command: "pnpm build && pnpm start",
      url: "http://localhost:3000",
      reuseExistingServer: false,
      timeout: 240_000,
      env: {
        SKIP_ENV_VALIDATION: "1",
        DEER_FLOW_AUTH_DISABLED: "1",
        BETTER_AUTH_SECRET: "local-dev-secret",
        DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: "http://127.0.0.1:8012",
      },
    },
  ],
});

import { defineConfig, devices } from "@playwright/test";

const frontendPort = process.env.E2E_FRONTEND_PORT ?? "3000";
const gatewayPort = process.env.E2E_GATEWAY_PORT ?? "8011";
const frontendUrl = `http://localhost:${frontendPort}`;
const gatewayUrl = `http://localhost:${gatewayPort}`;
const gatewayInternalUrl = `http://127.0.0.1:${gatewayPort}`;

/**
 * Layer 2 of the record/replay e2e: the REAL Next.js frontend rendering data
 * from a REAL gateway whose LLM is the deterministic `ReplayChatModel` (no API
 * key). This is separate from `playwright.config.ts` (which mocks the backend)
 * so the mock-based suite is untouched.
 *
 * Two webServers are started: the replay gateway and the frontend pointed at
 * it. Auth-disabled mode is enabled on both servers so the no-cookie e2e
 * contract is covered; specs that need session cookies still register a
 * throwaway test account at runtime.
 */
export default defineConfig({
  testDir: "./tests/e2e-real-backend",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "html",
  timeout: 90_000,

  use: {
    baseURL: frontendUrl,
    trace: "on-first-retry",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: [
    {
      command: `uv run python scripts/run_replay_gateway.py --port ${gatewayPort} --cors ${frontendUrl}`,
      cwd: "../backend",
      url: `${gatewayUrl}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
      // Mount the test-only run/message seeder used by multi-run-order.spec.ts
      // (#3352). The endpoint exists only on this replay gateway, never in the
      // production app.
      env: {
        DEERFLOW_ENABLE_TEST_SEED: "1",
        DEER_FLOW_AUTH_DISABLED: "1",
      },
    },
    {
      command: "pnpm build && pnpm start",
      url: frontendUrl,
      reuseExistingServer: !process.env.CI,
      timeout: 240_000,
      env: {
        PORT: frontendPort,
        SKIP_ENV_VALIDATION: "1",
        DEER_FLOW_AUTH_DISABLED: "1",
        BETTER_AUTH_SECRET: "local-dev-secret",
        // Leave NEXT_PUBLIC_* unset so the frontend uses its built-in
        // next.config rewrites (same-origin proxy) instead of talking to the
        // gateway cross-origin — cross-origin fetches drop the auth cookies.
        // Just point that proxy at the replay gateway.
        DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: gatewayInternalUrl,
      },
    },
  ],
});

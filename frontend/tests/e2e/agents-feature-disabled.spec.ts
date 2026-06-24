import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Agents feature disabled", () => {
  test("shows disabled message and issues no /api/agents requests when feature is off", async ({
    page,
  }) => {
    // Track any request to the agents API — there should be none.
    const agentRequests: string[] = [];
    page.on("request", (req) => {
      if (req.url().includes("/api/agents")) {
        agentRequests.push(req.url());
      }
    });

    // Shell/auth endpoints + the agents API mock (which should never be hit).
    mockLangGraphAPI(page, { agents: [] });

    // Feature flag reports the agents API as disabled.
    await page.route("**/api/features", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ agents_api: { enabled: false } }),
      }),
    );

    await page.goto("/workspace/agents");

    // The "feature not enabled" message renders (en-US or zh-CN copy).
    await expect(page.getByText(/not enabled|未启用/)).toBeVisible({
      timeout: 15_000,
    });

    // Gate prevented every agents API call, including direct navigation.
    expect(agentRequests).toEqual([]);
  });
});

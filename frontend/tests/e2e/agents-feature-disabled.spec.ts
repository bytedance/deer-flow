import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Agents feature disabled", () => {
  test("shows disabled message and issues no /api/agents requests when feature is off", async ({
    page,
  }) => {
    // Track any request to the agents API — there should be none. Anchor the
    // match so it only catches the real agents routes (/api/agents,
    // /api/agents/check, /api/agents/{name}) and never a future unrelated
    // path that merely contains the substring.
    const AGENTS_API = /\/api\/agents(\/|$)/;
    const agentRequests: string[] = [];
    page.on("request", (req) => {
      if (AGENTS_API.test(new URL(req.url()).pathname)) {
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

    // The disabled message renders and directs the user to an administrator
    // (en-US or zh-CN copy) without leaking backend config details.
    await expect(
      page.getByText(/contact your administrator|联系管理员/i),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/config\.yaml|agents_api/i)).toHaveCount(0);

    // Gate prevented every agents API call, including direct navigation.
    expect(agentRequests).toEqual([]);
  });

  test("stays disabled (no 403 storm) when /api/features goes down after a known-disabled result", async ({
    page,
  }) => {
    const AGENTS_API = /\/api\/agents(\/|$)/;
    const agentRequests: string[] = [];
    page.on("request", (req) => {
      if (AGENTS_API.test(new URL(req.url()).pathname)) {
        agentRequests.push(req.url());
      }
    });

    mockLangGraphAPI(page, { agents: [] });

    // /api/features first reports disabled, then starts failing — simulating
    // an outage of the features endpoint after the flag is already known.
    let featuresUp = true;
    await page.route("**/api/features", (route) =>
      featuresUp
        ? route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ agents_api: { enabled: false } }),
          })
        : route.fulfill({
            status: 500,
            contentType: "application/json",
            body: "{}",
          }),
    );

    // First visit observes a definitive "disabled" and persists it.
    await page.goto("/workspace/agents");
    await expect(
      page.getByText(/contact your administrator|联系管理员/i),
    ).toBeVisible({ timeout: 15_000 });

    // The features endpoint now fails. A reload must NOT fail open and remount
    // the agents page (which would re-trigger the 403 storm of #3757); the
    // last-known "disabled" value is sticky.
    featuresUp = false;
    agentRequests.length = 0;
    await page.goto("/workspace/agents");
    await expect(
      page.getByText(/contact your administrator|联系管理员/i),
    ).toBeVisible({ timeout: 15_000 });
    expect(agentRequests).toEqual([]);
  });
});

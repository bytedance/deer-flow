import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test("custom agent automatic default does not become an account preference", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    agents: [{ name: "researcher", description: "Research agent" }],
  });
  const patches: unknown[] = [];
  let reads = 0;
  let allowModels!: () => void;
  const modelsReady = new Promise<void>((resolve) => {
    allowModels = resolve;
  });
  await page.route("**/api/agents/researcher", (route) =>
    route.fulfill({
      json: {
        name: "researcher",
        description: "Research agent",
        model: "agent-model",
        system_prompt: "Research",
        tools: [],
        skills: [],
      },
    }),
  );
  await page.route("**/api/models", async (route) => {
    // Do not let the auth-disabled fixture select a model before the account
    // is activated. The real agent page must then choose its configured model.
    await modelsReady;
    await route.fulfill({
      json: {
        models: [
          {
            name: "first-model",
            display_name: "First Model",
            supports_thinking: true,
          },
          {
            name: "agent-model",
            display_name: "Agent Model",
            supports_thinking: true,
          },
        ],
      },
    });
  });
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        id: "00000000-0000-0000-0000-000000000027",
        email: "agent@example.com",
        system_role: "admin",
        needs_setup: false,
      },
    }),
  );
  await page.route("**/api/v1/auth/preferences", async (route) => {
    if (route.request().method() === "PATCH") {
      patches.push(route.request().postDataJSON());
      await route.fulfill({ status: 204 });
    } else {
      reads++;
      await route.fulfill({
        json: {
          model_name: null,
          mode: null,
          reasoning_effort: null,
          notification_enabled: true,
        },
      });
    }
  });
  await page.goto("/workspace/agents/researcher/chats/new");
  await page
    .locator("[data-sidebar='sidebar']")
    .getByRole("button", { name: /Settings and more/ })
    .click();
  await page.keyboard.press("Escape");
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange")),
  );
  await expect.poll(() => reads).toBe(1);
  allowModels();
  await expect(
    page.getByRole("button", { name: "Agent Model", exact: true }),
  ).toBeVisible();
  // Flush the local outbox cycle through a completed server read, so this also
  // catches a PATCH that would otherwise arrive just after the UI assertion.
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect.poll(() => reads).toBe(2);
  expect(patches).toEqual([]);
  // Explicit model selections on this same page must still be synchronized.
  await page.getByRole("button", { name: "Agent Model", exact: true }).click();
  await page.getByRole("option").filter({ hasText: "First Model" }).click();
  await expect.poll(() => patches).toEqual([{ model_name: "first-model" }]);
});

test("automatic model fallback cannot overwrite a slowly loaded account preference", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  const patches: unknown[] = [];
  let requested = false;
  let release!: () => void;
  const delayed = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/models", (route) =>
    route.fulfill({
      json: {
        models: [
          { name: "model-a", display_name: "Model A", supports_thinking: true },
          { name: "model-b", display_name: "Model B", supports_thinking: true },
        ],
      },
    }),
  );
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        id: "00000000-0000-0000-0000-000000000026",
        email: "model@example.com",
        system_role: "admin",
        needs_setup: false,
      },
    }),
  );
  await page.route("**/api/v1/auth/preferences", async (route) => {
    if (route.request().method() === "PATCH") {
      patches.push(route.request().postDataJSON());
      await route.fulfill({ status: 204 });
      return;
    }
    requested = true;
    await delayed;
    await route.fulfill({
      json: {
        model_name: "model-b",
        mode: "pro",
        reasoning_effort: "high",
        notification_enabled: true,
      },
    });
  });
  await page.goto("/workspace/chats/new");
  // Wait for actual hydration before refreshing the auth-disabled fixture's
  // AuthProvider into a session account with a deliberately slow preference GET.
  await page
    .locator("[data-sidebar='sidebar']")
    .getByRole("button", { name: /Settings and more/ })
    .click();
  await page.keyboard.press("Escape");
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange")),
  );
  await expect.poll(() => requested).toBe(true);
  await expect(
    page.getByRole("button", { name: "Model A", exact: true }),
  ).toBeVisible();
  release();
  await expect(
    page.getByRole("button", { name: "Model B", exact: true }),
  ).toBeVisible();
  expect(patches).toEqual([]);
});

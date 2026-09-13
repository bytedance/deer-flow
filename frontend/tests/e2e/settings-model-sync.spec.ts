import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

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

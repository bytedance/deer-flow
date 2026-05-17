import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Landing page", () => {
  test("renders the header and hero section", async ({ page }) => {
    await page.goto("/");

    // Header brand name
    await expect(
      page.locator("header h1", { hasText: "EHM AI 工作台" }),
    ).toBeVisible();

    // "进入工作台" call-to-action link in hero
    await expect(
      page.getByRole("link", { name: /进入工作台/ }).first(),
    ).toBeVisible();
  });

  test("Get Started link navigates to workspace", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/");

    const getStarted = page.getByRole("link", { name: /进入工作台/ }).first();
    await getStarted.click();

    // Should redirect to /workspace/chats/new
    await page.waitForURL("**/workspace/chats/new");
    await expect(page).toHaveURL(/\/workspace\/chats\/new/);
  });
});

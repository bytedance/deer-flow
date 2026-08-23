import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Landing page", () => {
  test("renders the header and hero section", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.locator("header").first().getByText("DeerFlow", { exact: true }),
    ).toBeVisible();
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("h1")).toContainText("DeerFlow");

    // "Get Started" call-to-action button in hero
    await expect(
      page.getByRole("link", { name: /get started/i }),
    ).toBeVisible();
  });

  for (const width of [320, 375, 390]) {
    test(`does not overflow at ${width}px width`, async ({ page }) => {
      await page.setViewportSize({ width, height: 812 });
      await page.goto("/");

      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
        .toBeLessThanOrEqual(width);
      await expect(page.locator("main").first()).toBeInViewport();
    });
  }

  test("Get Started link navigates to workspace", async ({ page }, testInfo) => {
    mockLangGraphAPI(page);

    await page.goto("/");

    const getStarted = page.getByRole("link", { name: /get started/i });
    await getStarted.click();

    if (testInfo.project.name === "static-website") {
      // In static mode `/workspace` redirects to the demo thread, not /chats/new.
      await page.waitForURL("**/workspace/chats/21cfea46-34bd-4aa6-9e1f-3009452fbeb9");
      await expect(page).toHaveURL(
        /\/workspace\/chats\/21cfea46-34bd-4aa6-9e1f-3009452fbeb9/,
      );
    } else {
      // Full deployment: `/` redirects into the app, Get Started opens a new chat.
      await page.waitForURL("**/workspace/chats/new");
      await expect(page).toHaveURL(/\/workspace\/chats\/new/);
    }
  });
});

import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Landing page", () => {
  test("renders the header, hero, and deerflow:// architecture diagram", async ({
    page,
  }) => {
    await page.goto("/");

    await expect(
      page.locator("header").first().getByText("DeerFlow", { exact: true }),
    ).toBeVisible();
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("h1")).toContainText("DeerFlow");

    // "Get Started" call-to-action button in hero
    await expect(
      page.locator("main").getByRole("link", { name: /get started/i }),
    ).toBeVisible();

    // Interactive architecture diagram renders deerflow://
    const diagram = page.locator("#architecture");
    await expect(diagram).toBeVisible();
    await expect(diagram.getByText("deerflow://").first()).toBeVisible();
  });

  test("defaults to light theme and toggles dark mode", async ({ page }) => {
    await page.goto("/");

    const html = page.locator("html");
    await expect(html).not.toHaveClass(/\bdark\b/);

    await page.getByRole("button", { name: /switch to dark theme/i }).click();
    await expect(html).toHaveClass(/\bdark\b/);

    await page.getByRole("button", { name: /switch to light theme/i }).click();
    await expect(html).not.toHaveClass(/\bdark\b/);
  });

  test("toggles landing copy between English and Chinese", async ({ page }) => {
    await page.goto("/");

    await expect(page.locator("h1")).toContainText(
      "DeerFlow: Open-Source SuperAgent Harness.",
    );

    await page.getByRole("button", { name: /switch language/i }).click();
    await page.getByRole("menuitem", { name: /简体中文/ }).click();

    await expect(page.locator("h1")).toContainText(
      "DeerFlow：开源超级智能体引擎",
    );
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");

    await page.getByRole("button", { name: "切换语言" }).click();
    await page.getByRole("menuitem", { name: /English/ }).click();

    await expect(page.locator("h1")).toContainText(
      "DeerFlow: Open-Source SuperAgent Harness.",
    );
    await expect(page.locator("html")).toHaveAttribute("lang", "en-US");
  });

  test("shows announcement banner and allows dismissal", async ({ page }) => {
    await page.goto("/");

    const dismissButton = page.getByRole("button", {
      name: /dismiss announcement/i,
    });
    await expect(dismissButton).toBeVisible();

    await dismissButton.click();
    await expect(dismissButton).toBeHidden();
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

  test("Get Started link navigates to workspace", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/");

    const getStarted = page
      .locator("main")
      .getByRole("link", { name: /get started/i });
    await getStarted.click();

    // Should redirect to /workspace/chats/new
    await page.waitForURL("**/workspace/chats/new");
    await expect(page).toHaveURL(/\/workspace\/chats\/new/);
  });
});

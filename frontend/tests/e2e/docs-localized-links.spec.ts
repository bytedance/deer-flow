import { expect, test } from "@playwright/test";

test.describe("Localized documentation links", () => {
  test("keeps English card navigation in the English docs", async ({
    page,
  }) => {
    await page.goto("/en/docs/introduction/core-concepts");

    const card = page.locator("a.nextra-card", { hasText: "Why DeerFlow" });
    await expect(card).toHaveAttribute(
      "href",
      "/en/docs/introduction/why-deerflow",
    );

    await card.click();
    await expect(page).toHaveURL(/\/en\/docs\/introduction\/why-deerflow$/);
    await expect(page.locator("main h1")).toContainText("Why DeerFlow");
  });

  test("keeps Chinese card navigation in the Chinese docs", async ({
    page,
  }) => {
    await page.goto("/zh/docs/introduction/core-concepts");

    const card = page.locator("a.nextra-card", { hasText: "Harness 与应用" });
    await expect(card).toHaveAttribute(
      "href",
      "/zh/docs/introduction/harness-vs-app",
    );

    await card.click();
    await expect(page).toHaveURL(/\/zh\/docs\/introduction\/harness-vs-app$/);
    await expect(page.locator("main h1")).toContainText("Harness 与应用");
  });

  test("localizes regular Markdown links", async ({ page }) => {
    await page.goto("/en/docs/application/workspace-usage");

    const link = page
      .locator("main")
      .getByRole("link", { name: "Agents and Threads" })
      .first();
    await expect(link).toHaveAttribute(
      "href",
      "/en/docs/application/agents-and-threads",
    );

    await link.click();
    await expect(page).toHaveURL(
      /\/en\/docs\/application\/agents-and-threads$/,
    );
    await expect(page.locator("main h1")).toContainText("Agents and Threads");
  });
});

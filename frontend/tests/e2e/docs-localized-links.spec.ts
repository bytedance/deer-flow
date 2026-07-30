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

  test("excludes non-documentation app routes from the docs navigation", async ({
    page,
  }) => {
    await page.goto("/en/docs");

    const invalidDocsLinks = page.locator(
      ["auth", "blog", "login", "setup", "workspace"]
        .map((root) => `a[href^="/en/docs/${root}"]`)
        .join(", "),
    );
    await expect(invalidDocsLinks).toHaveCount(0);
  });

  test("uses valid repository links for documentation feedback and edits", async ({
    page,
  }) => {
    await page.goto("/en/docs/application/quick-start");

    await expect(
      page.getByRole("link", { name: "Question? Give us feedback" }),
    ).toHaveAttribute("href", /github\.com\/bytedance\/deer-flow\/issues\/new/);
    await expect(
      page.getByRole("link", { name: "Edit this page" }),
    ).toHaveAttribute(
      "href",
      "https://github.com/bytedance/deer-flow/tree/main/frontend/src/content/en/application/quick-start.mdx",
    );
  });
});

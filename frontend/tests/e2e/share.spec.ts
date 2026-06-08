import { expect, test } from "@playwright/test";

const SHARE_ID = "share-public-1";

test.describe("Public share page", () => {
  test("renders a shared answer snapshot without workspace APIs", async ({
    page,
  }) => {
    await page.route(`**/api/shares/${SHARE_ID}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          share_id: SHARE_ID,
          title: "Research summary",
          created_at: "2026-01-01T00:00:00Z",
          messages: [
            {
              type: "human",
              id: "human-1",
              content: [{ type: "text", text: "Summarize the report" }],
            },
            {
              type: "ai",
              id: "ai-1",
              content: "The report highlights revenue growth.",
            },
          ],
        }),
      }),
    );

    await page.goto(`/share/${SHARE_ID}`);

    await expect(
      page.getByRole("heading", { name: "Research summary" }),
    ).toBeVisible();
    await expect(page.getByText("Summarize the report")).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      page.getByText("The report highlights revenue growth."),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /share/i })).toHaveCount(0);
  });

  test("shows the public share load error", async ({ page }) => {
    await page.route("**/api/shares/missing-share", (route) =>
      route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Share not found" }),
      }),
    );

    await page.goto("/share/missing-share");

    await expect(page.getByText("Share not found (404)")).toBeVisible({
      timeout: 15_000,
    });
  });
});

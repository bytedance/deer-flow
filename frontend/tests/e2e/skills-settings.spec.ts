import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Skill gallery", () => {
  test("shows a failure and keeps the toggle state when disabling a skill is rejected", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      skills: [
        {
          name: "toggle-skill",
          description: "Test skill",
          category: "public",
          enabled: true,
        },
      ],
    });

    void page.route("**/api/suggestions/config", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ enabled: false }),
      });
    });

    void page.route("**/api/skills/toggle-skill", (route) => {
      if (route.request().method() === "PUT") {
        return route.fulfill({
          status: 403,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Skill toggle denied" }),
        });
      }
      return route.fallback();
    });

    await page.goto("/workspace/capabilities?tab=skills");
    const toggle = page.getByRole("switch", { name: /toggle-skill/ });

    await expect(page.getByText("toggle-skill")).toBeVisible();
    await expect(toggle).toBeChecked();
    await toggle.click();

    await expect(page.getByText("Skill toggle denied")).toBeVisible();
    await expect(toggle).toBeChecked();
  });
});

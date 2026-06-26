import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

async function openSkillSettings(page: Page) {
  await page.goto("/workspace/chats/new");
  const sidebar = page.locator("[data-sidebar='sidebar']");
  await sidebar.getByRole("button", { name: /Settings and more/ }).click();
  await page.getByRole("menuitem", { name: "Settings" }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Skills" }).click();
  return dialog;
}

test.describe("Skill settings", () => {
  test("shows a failure and keeps the toggle state when enabling a skill is rejected", async ({
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

    const dialog = await openSkillSettings(page);
    const toggle = dialog.getByRole("switch");

    await expect(dialog.getByText("toggle-skill")).toBeVisible();
    await expect(toggle).toBeChecked();
    await toggle.click();

    await expect(page.getByText("Skill toggle denied")).toBeVisible();
    await expect(toggle).toBeChecked();
  });
});

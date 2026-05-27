import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Sidebar navigation", () => {
  test("agents section is collapsible", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");

    // Agents section trigger should be visible
    const agentsTrigger = sidebar.getByText("智能体").first();
    await expect(agentsTrigger).toBeVisible({ timeout: 15_000 });
  });

  test("Tools menu is collapsible", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");

    // Tools menu trigger should be visible
    const toolsTrigger = sidebar.getByText("工具").first();
    await expect(toolsTrigger).toBeVisible({ timeout: 15_000 });

    // Initially collapsed - knowledge bases link should not be visible
    const kbLink = sidebar.locator("a[href='/workspace/knowledge-bases']");
    await expect(kbLink).not.toBeVisible({ timeout: 3_000 });

    // Click to expand
    await toolsTrigger.click();

    // Now knowledge bases should be visible
    await expect(kbLink).toBeVisible({ timeout: 5_000 });

    // Click again to collapse
    await toolsTrigger.click();
    await expect(kbLink).not.toBeVisible({ timeout: 3_000 });
  });

  test("Tools menu state persists in localStorage", async ({ page }) => {
    mockLangGraphAPI(page);

    // Pre-set localStorage to expanded state
    await page.goto("/workspace/chats/new");
    await page.evaluate(() => {
      localStorage.setItem("sidebar-tools-collapsed", "false");
    });

    // Reload page
    await page.reload();

    const sidebar = page.locator("[data-sidebar='sidebar']");
    const kbLink = sidebar.locator("a[href='/workspace/knowledge-bases']");

    // Should be expanded after reload
    await expect(kbLink).toBeVisible({ timeout: 5_000 });

    // Pre-set localStorage to collapsed state
    await page.evaluate(() => {
      localStorage.setItem("sidebar-tools-collapsed", "true");
    });

    await page.reload();

    // Should be collapsed after reload
    await expect(kbLink).not.toBeVisible({ timeout: 3_000 });
  });
});

test.describe("Landing page", () => {
  test("hero section has enter workspace button", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/");

    // "进入工作台" button should be visible
    const enterWorkspace = page.getByRole("link", { name: /进入工作台/ });
    await expect(enterWorkspace).toBeVisible({ timeout: 10_000 });

    await enterWorkspace.click();
    await page.waitForURL("**/workspace");
  });

  test("feature cards are displayed", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByText("实时监测")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("智能诊断")).toBeVisible();
    await expect(page.getByText("运行报告")).toBeVisible();
    await expect(page.getByText("对话操作")).toBeVisible();
  });
});

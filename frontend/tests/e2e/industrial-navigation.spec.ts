import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Industrial navigation", () => {
  test("industrial workflows appear first in sidebar", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");

    // Industrial section label should be visible
    await expect(sidebar.getByText("工业智能")).toBeVisible({ timeout: 15_000 });

    // Industrial workflow links should be present
    const monitoringLink = sidebar.locator(
      "a[href='/workspace/agents/monitoring-analysis/chats/new']"
    );
    const diagnosisLink = sidebar.locator(
      "a[href='/workspace/agents/device-diagnosis/chats/new']"
    );
    const trendLink = sidebar.locator(
      "a[href='/workspace/agents/trend-report/chats/new']"
    );

    await expect(monitoringLink).toBeVisible({ timeout: 10_000 });
    await expect(diagnosisLink).toBeVisible({ timeout: 10_000 });
    await expect(trendLink).toBeVisible({ timeout: 10_000 });

    // Get all menu items and verify industrial items come before general items
    const menuItems = sidebar.locator("[data-sidebar='menu-button']");
    const firstItemText = await menuItems.first().textContent();
    expect(firstItemText).toContain("工业智能");
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

  test("industrial workflow links navigate correctly", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    const monitoringLink = sidebar.locator(
      "a[href='/workspace/agents/monitoring-analysis/chats/new']"
    );

    await expect(monitoringLink).toBeVisible({ timeout: 15_000 });
    await monitoringLink.click();

    await page.waitForURL("**/workspace/agents/monitoring-analysis/chats/new");
    await expect(page).toHaveURL(
      /\/workspace\/agents\/monitoring-analysis\/chats\/new/
    );
  });
});

test.describe("Landing page Quick Access", () => {
  test("Quick Access section shows industrial workflows", async ({ page }) => {
    await page.goto("/");

    // Quick Access heading should be visible
    await expect(page.getByText("Quick Access")).toBeVisible({ timeout: 10_000 });

    // Three workflow cards should be present
    await expect(page.getByText("设备监测")).toBeVisible();
    await expect(page.getByText("故障诊断")).toBeVisible();
    await expect(page.getByText("趋势报告")).toBeVisible();
  });

  test("Quick Access cards link to correct workflows", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/");

    // Click monitoring card
    const monitoringCard = page.locator("a", { hasText: "设备监测" }).first();
    await expect(monitoringCard).toBeVisible({ timeout: 10_000 });
    await monitoringCard.click();

    await page.waitForURL("**/workspace/agents/monitoring-analysis/chats/new");
    await expect(page).toHaveURL(
      /\/workspace\/agents\/monitoring-analysis\/chats\/new/
    );
  });

  test("hero section has industrial workflow quick start button", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/");

    // "开始监测" button should be visible
    const startMonitoring = page.getByRole("link", { name: /开始监测/ });
    await expect(startMonitoring).toBeVisible({ timeout: 10_000 });

    await startMonitoring.click();
    await page.waitForURL("**/workspace/agents/monitoring-analysis/chats/new");
  });
});

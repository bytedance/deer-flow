import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Industrial Onboarding - New User Flow", () => {
  test.beforeEach(async ({ page }) => {
    mockLangGraphAPI(page);
    // Clear local storage to simulate new user
    await page.addInitScript(() => {
      localStorage.clear();
    });
  });

  test("new user sees onboarding overlay and completes full flow", async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new");

    // Step 0: Welcome screen should appear
    const overlay = page.locator(".fixed.inset-0.z-\\[100\\]");
    await expect(overlay).toBeVisible({ timeout: 5000 });

    await expect(page.getByText("欢迎使用工业智能平台")).toBeVisible();
    await expect(page.getByText("1 / 5")).toBeVisible();

    // Click Next to proceed to device selection
    await page.getByRole("button", { name: "下一步" }).click();

    // Step 1: Device selection
    await expect(page.getByText("选择设备或场景")).toBeVisible();
    await expect(page.getByText("2 / 5")).toBeVisible();

    // Select a sample device
    const deviceButtons = page.locator(
      'button:has-text("P-101A"), button:has-text("C-203B"), button:has-text("V-301")'
    );
    await expect(deviceButtons.first()).toBeVisible();
    await deviceButtons.first().click();

    // Next button should now be enabled
    await page.getByRole("button", { name: "下一步" }).click();

    // Step 2: Quick analysis
    await expect(page.getByText("执行快速诊断")).toBeVisible();
    await expect(page.getByText("3 / 5")).toBeVisible();

    // Click "Run Analysis" button
    await page.getByRole("button", { name: "运行分析" }).click();

    // Wait for analysis to complete (2 second delay in component)
    await expect(page.getByText("✓ 查看报告")).toBeVisible({
      timeout: 5000,
    });

    await page.getByRole("button", { name: "下一步" }).click();

    // Step 3: View report
    await expect(page.getByText("查看报告")).toBeVisible();
    await expect(page.getByText("4 / 5")).toBeVisible();
    await expect(page.getByText("✓ Vibration levels normal")).toBeVisible();

    await page.getByRole("button", { name: "下一步" }).click();

    // Step 4: Finish
    await expect(page.getByText("开始使用")).toBeVisible();
    await expect(page.getByText("5 / 5")).toBeVisible();

    // Click "Start Using" button
    await page.getByRole("button", { name: "开始使用工作台" }).click();

    // Overlay should disappear
    await expect(overlay).not.toBeVisible({ timeout: 5000 });

    // Verify local storage was updated
    const settings = await page.evaluate(() => {
      const stored = localStorage.getItem("local-settings");
      return stored ? JSON.parse(stored) : null;
    });

    expect(settings).not.toBeNull();
    expect(settings.onboarding.industrialCompleted).toBe(true);
    expect(settings.onboarding.industrialOperations).toContain(
      "device_diagnosis"
    );
    expect(settings.onboarding.industrialOperations).toContain(
      "monitoring_analysis"
    );
    expect(settings.onboarding.industrialOperations).toContain("trend_report");
  });

  test("user can skip onboarding", async ({ page }) => {
    await page.goto("/workspace/chats/new");

    // Overlay should appear
    const overlay = page.locator(".fixed.inset-0.z-\\[100\\]");
    await expect(overlay).toBeVisible({ timeout: 5000 });

    // Click Skip button
    await page.getByRole("button", { name: "跳过" }).click();

    // Overlay should disappear
    await expect(overlay).not.toBeVisible({ timeout: 5000 });

    // Verify onboarding was marked as completed
    const settings = await page.evaluate(() => {
      const stored = localStorage.getItem("local-settings");
      return stored ? JSON.parse(stored) : null;
    });

    expect(settings).not.toBeNull();
    expect(settings.onboarding.industrialCompleted).toBe(true);
  });

  test("user can close onboarding with X button", async ({ page }) => {
    await page.goto("/workspace/chats/new");

    // Overlay should appear
    const overlay = page.locator(".fixed.inset-0.z-\\[100\\]");
    await expect(overlay).toBeVisible({ timeout: 5000 });

    // Click close (X) button
    await page.getByLabel("Close").click();

    // Overlay should disappear
    await expect(overlay).not.toBeVisible({ timeout: 5000 });

    // Verify onboarding was marked as completed
    const settings = await page.evaluate(() => {
      const stored = localStorage.getItem("local-settings");
      return stored ? JSON.parse(stored) : null;
    });

    expect(settings).not.toBeNull();
    expect(settings.onboarding.industrialCompleted).toBe(true);
  });

  test("user can navigate back and forth", async ({ page }) => {
    await page.goto("/workspace/chats/new");

    const overlay = page.locator(".fixed.inset-0.z-\\[100\\]");
    await expect(overlay).toBeVisible({ timeout: 5000 });

    // Step 0: Welcome
    await expect(page.getByText("1 / 5")).toBeVisible();
    await page.getByRole("button", { name: "下一步" }).click();

    // Step 1: Device selection
    await expect(page.getByText("2 / 5")).toBeVisible();

    // Back button should not be visible on step 0, but visible on step 1
    await expect(page.getByRole("button", { name: "上一步" })).toBeVisible();
    await page.getByRole("button", { name: "上一步" }).click();

    // Back to Step 0
    await expect(page.getByText("1 / 5")).toBeVisible();
  });
});

test.describe("Industrial Onboarding - Existing User", () => {
  test("user with existing industrial operations does not see onboarding", async ({
    page,
  }) => {
    mockLangGraphAPI(page);

    // Set up local storage with existing industrial operations
    await page.addInitScript(() => {
      const settings = {
        onboarding: {
          industrialCompleted: false,
          industrialOperations: ["device_diagnosis", "monitoring_analysis"],
        },
      };
      localStorage.setItem("local-settings", JSON.stringify(settings));
    });

    await page.goto("/workspace/chats/new");

    // Wait a bit to ensure page is loaded
    await page.waitForTimeout(1000);

    // Overlay should NOT appear
    const overlay = page.locator(".fixed.inset-0.z-\\[100\\]");
    await expect(overlay).not.toBeVisible({ timeout: 3000 });
  });

  test("user who completed onboarding does not see it again", async ({
    page,
  }) => {
    mockLangGraphAPI(page);

    // Set up local storage with completed onboarding
    await page.addInitScript(() => {
      const settings = {
        onboarding: {
          industrialCompleted: true,
          industrialOperations: [],
        },
      };
      localStorage.setItem("local-settings", JSON.stringify(settings));
    });

    await page.goto("/workspace/chats/new");

    // Wait a bit to ensure page is loaded
    await page.waitForTimeout(1000);

    // Overlay should NOT appear
    const overlay = page.locator(".fixed.inset-0.z-\\[100\\]");
    await expect(overlay).not.toBeVisible({ timeout: 3000 });
  });
});

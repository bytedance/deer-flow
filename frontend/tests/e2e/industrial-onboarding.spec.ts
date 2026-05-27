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
    await expect(page.getByText("选择要分析的设备")).toBeVisible();
    await expect(page.getByText("2 / 5")).toBeVisible();

    // Select a sample device
    const deviceButtons = page.locator(
      'button:has-text("P-101A"), button:has-text("C-201"), button:has-text("R-301")'
    );
    await expect(deviceButtons.first()).toBeVisible();
    await deviceButtons.first().click();

    // Next button should now be enabled
    await page.getByRole("button", { name: "下一步" }).click();

    // Step 2: Quick analysis
    await expect(page.getByText("执行快速分析")).toBeVisible();
    await expect(page.getByText("3 / 5")).toBeVisible();

    // Click "Start Analysis" button
    await page.getByRole("button", { name: "开始分析" }).click();

    // Wait for analysis to complete (2 second delay in component)
    await expect(page.getByText("✓ 查看结果")).toBeVisible({
      timeout: 5000,
    });

    await page.getByRole("button", { name: "下一步" }).click();

    // Step 3: View report
    await expect(page.getByText("查看结果")).toBeVisible();
    await expect(page.getByText("4 / 5")).toBeVisible();
    await expect(page.getByText("✓ Vibration levels normal")).toBeVisible();

    await page.getByRole("button", { name: "下一步" }).click();

    // Step 4: Finish
    await expect(page.getByText("准备就绪")).toBeVisible();
    await expect(page.getByText("5 / 5")).toBeVisible();

    // Click "Start Using" button
    await page.getByRole("button", { name: "开始使用" }).click();

    // Overlay should disappear
    await expect(overlay).not.toBeVisible({ timeout: 5000 });

    // Should navigate to new chat page (industrial workspace)
    await expect(page).toHaveURL(/\/workspace\/chats\/new/);

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
    await expect(page.getByRole("button", { name: "返回" })).toBeVisible();
    await page.getByRole("button", { name: "返回" }).click();

    // Back to Step 0
    await expect(page.getByText("1 / 5")).toBeVisible();
  });
});

test.describe("Industrial Onboarding - Simplified Flow", () => {
  test.beforeEach(async ({ page }) => {
    mockLangGraphAPI(page);
    await page.addInitScript(() => {
      localStorage.clear();
    });
  });

  test("no skip-to-foundation button exists", async ({ page }) => {
    await page.goto("/workspace/chats/new");

    const overlay = page.locator(".fixed.inset-0.z-\\[100\\]");
    await expect(overlay).toBeVisible({ timeout: 5000 });

    // Only "跳过" (Skip) button should exist — no "skip to foundation" variant
    const skipButtons = page.getByRole("button", { name: "跳过" });
    await expect(skipButtons).toHaveCount(1);

    // No button containing "foundation" or "基础" should appear anywhere in the overlay
    await expect(
      overlay.getByRole("button", { name: /基础|foundation/i })
    ).not.toBeVisible();

    // Step through all 5 steps — still no foundation escape hatch
    for (let step = 0; step < 4; step++) {
      await expect(page.getByText(`${step + 1} / 5`)).toBeVisible();
      await expect(
        overlay.getByRole("button", { name: /基础|foundation/i })
      ).not.toBeVisible();

      if (step === 1) {
        // Need to select a device on step 1
        await page
          .locator(
            'button:has-text("P-101A"), button:has-text("C-201"), button:has-text("R-301")'
          )
          .first()
          .click();
      }
      if (step === 2) {
        // Need to run analysis on step 2 and wait for completion
        await page.getByRole("button", { name: "开始分析" }).click();
        await expect(page.getByText("✓ 查看结果")).toBeVisible({
          timeout: 5000,
        });
      }
      await page.getByRole("button", { name: "下一步" }).click();
    }

    // Step 5: finish — still no foundation button
    await expect(page.getByText("5 / 5")).toBeVisible();
    await expect(
      overlay.getByRole("button", { name: /基础|foundation/i })
    ).not.toBeVisible();
  });

  test("onboarding messaging is industrial-first throughout", async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new");

    const overlay = page.locator(".fixed.inset-0.z-\\[100\\]");
    await expect(overlay).toBeVisible({ timeout: 5000 });

    // Step 0: Industrial-first welcome
    await expect(page.getByText("欢迎使用工业智能平台")).toBeVisible();
    await expect(
      page.getByText(/监测设备健康.*诊断故障.*生成报告/)
    ).toBeVisible();

    // Step 1: Device-focused selection
    await page.getByRole("button", { name: "下一步" }).click();
    await expect(page.getByText("选择要分析的设备")).toBeVisible();
    await expect(page.getByText("P-101A 离心泵")).toBeVisible();
    await expect(page.getByText("C-201 压缩机")).toBeVisible();

    // Select device
    await page.getByText("P-101A 离心泵").click();
    await page.getByRole("button", { name: "下一步" }).click();

    // Step 2: Industrial analysis (vibration data)
    await expect(page.getByText("执行快速分析")).toBeVisible();
    await expect(page.getByText(/振动数据/)).toBeVisible();

    await page.getByRole("button", { name: "开始分析" }).click();
    await expect(page.getByText("✓ 查看结果")).toBeVisible({ timeout: 5000 });
    await page.getByRole("button", { name: "下一步" }).click();

    // Step 3: Report with industrial findings
    await expect(page.getByText("查看结果")).toBeVisible();
    await expect(page.getByText("Vibration levels normal")).toBeVisible();
    await expect(page.getByText("No anomalies detected")).toBeVisible();
    await page.getByRole("button", { name: "下一步" }).click();

    // Step 4: Industrial-first finish messaging
    await expect(page.getByText("准备就绪")).toBeVisible();
    await expect(
      page.getByText(/监测设备.*运行诊断.*生成报告/)
    ).toBeVisible();
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

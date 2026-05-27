import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

function mockMigrationAPIs(
  page: Page,
  options?: {
    prompted?: boolean;
    completed?: boolean;
    accepted?: boolean;
  },
) {
  const state = {
    prompted: options?.prompted ?? false,
    completed: options?.completed ?? false,
    accepted: options?.accepted ?? false,
    prompted_at: options?.prompted ? "2026-05-26T00:00:00Z" : null,
    completed_at: options?.completed ? "2026-05-26T00:00:00Z" : null,
  };

  void page.route("**/api/tenant/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        tenant_id: "default",
        is_active: true,
        name: "Default",
        found: true,
      }),
    }),
  );

  void page.route("**/api/tenants/*/migration-status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        tenant_id: "default",
        ...state,
      }),
    }),
  );

  void page.route("**/api/tenants/*/mark-migration-prompted", (route) => {
    if (route.request().method() === "POST") {
      state.prompted = true;
      state.prompted_at = new Date().toISOString();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          tenant_id: "default",
          ...state,
        }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/tenants/*/migrate-industrial", (route) => {
    if (route.request().method() === "POST") {
      state.completed = true;
      state.accepted = true;
      state.completed_at = new Date().toISOString();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          tenant_id: "default",
          enabled_count: 5,
          skill_names: [
            "vibration-diagnosis",
            "monitoring-analysis",
            "trend-report",
            "failure-analysis",
            "inspection-summary",
          ],
        }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/tenants/*/decline-migration", (route) => {
    if (route.request().method() === "POST") {
      state.completed = true;
      state.accepted = false;
      state.completed_at = new Date().toISOString();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          tenant_id: "default",
          message: "Migration declined",
        }),
      });
    }
    return route.fallback();
  });
}

test.describe("Industrial Migration Dialog", () => {
  test("dialog appears when migration has not been prompted", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    mockMigrationAPIs(page, { prompted: false, completed: false });

    await page.goto("/workspace/chats/new");

    const dialog = page.locator("[data-slot='dialog-content']");
    await expect(dialog).toBeVisible({ timeout: 15_000 });

    await expect(page.getByText("工业智能功能已就绪")).toBeVisible();
    await expect(page.getByText("Industrial Intelligence is Ready")).toBeVisible();
    await expect(
      page.getByText("启用工业智能 / Enable Industrial Intelligence"),
    ).toBeVisible();
  });

  test("dialog shows industrial skills list", async ({ page }) => {
    mockLangGraphAPI(page);
    mockMigrationAPIs(page, { prompted: false, completed: false });

    await page.goto("/workspace/chats/new");

    const dialog = page.locator("[data-slot='dialog-content']");
    await expect(dialog).toBeVisible({ timeout: 15_000 });

    await expect(page.getByText("设备振动诊断")).toBeVisible();
    await expect(page.getByText("设备监测分析")).toBeVisible();
    await expect(page.getByText("趋势报告")).toBeVisible();
    await expect(page.getByText("故障分析")).toBeVisible();
    await expect(page.getByText("巡检总结")).toBeVisible();
  });

  test("accepting migration enables skills and closes dialog", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    mockMigrationAPIs(page, { prompted: false, completed: false });

    await page.goto("/workspace/chats/new");

    const dialog = page.locator("[data-slot='dialog-content']");
    await expect(dialog).toBeVisible({ timeout: 15_000 });

    await page
      .getByRole("button", { name: /启用工业智能/i })
      .click();

    await expect(dialog).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/已启用 5 个工业智能技能/)).toBeVisible({
      timeout: 5_000,
    });
  });

  test("declining migration closes dialog without enabling skills", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    mockMigrationAPIs(page, { prompted: false, completed: false });

    await page.goto("/workspace/chats/new");

    const dialog = page.locator("[data-slot='dialog-content']");
    await expect(dialog).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: /暂不启用/i }).click();

    await expect(dialog).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/已启用/)).not.toBeVisible({ timeout: 2_000 });
  });

  test("dialog does not appear when migration already completed", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    mockMigrationAPIs(page, { prompted: true, completed: true, accepted: true });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    const dialog = page.locator("[data-slot='dialog-content']");
    await expect(dialog).not.toBeVisible({ timeout: 3_000 });
  });

  test("dialog does not appear when migration was declined", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    mockMigrationAPIs(page, {
      prompted: true,
      completed: true,
      accepted: false,
    });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    const dialog = page.locator("[data-slot='dialog-content']");
    await expect(dialog).not.toBeVisible({ timeout: 3_000 });
  });
});

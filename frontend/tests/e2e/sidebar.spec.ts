import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Sidebar navigation", () => {
  test("sidebar contains Chats and Agents nav links", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    // Sidebar uses data-sidebar="menu-button" with asChild rendering on <Link>
    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(sidebar.locator("a[href='/workspace/chats']")).toBeVisible({
      timeout: 15_000,
    });
    await expect(sidebar.locator("a[href='/workspace/agents']")).toBeVisible();
  });

  test("Agents link navigates to agents page", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    const agentsLink = sidebar.locator("a[href='/workspace/agents']");
    await expect(agentsLink).toBeVisible({ timeout: 15_000 });
    await agentsLink.click();

    await page.waitForURL("**/workspace/agents");
    await expect(page).toHaveURL(/\/workspace\/agents/);
  });

  test("report history nav item shows collapsible sub-list with report threads", async ({ page }) => {
    mockLangGraphAPI(page, {
      agents: [
        {
          name: "ai-report--custom",
          description: "AI 报告子智能体",
          display_name: "AI 报告",
          icon: null,
          model: null,
          tool_groups: null,
          skills: null,
          mcp_servers: null,
          tags: ["report", "custom"],
          source: "builtin",
          editable: false,
          enabled: true,
        },
        {
          name: "main-agent",
          description: "主智能体",
          display_name: "主智能体",
          icon: null,
          model: null,
          tool_groups: null,
          skills: null,
          mcp_servers: null,
          tags: null,
          source: "builtin",
          editable: false,
          enabled: true,
          nav_items: [
            { path: "/workspace/report-runs", label: "报告历史", icon: "History" },
          ],
        },
      ],
      threads: [
        {
          thread_id: "thread-report-aaa",
          title: "日报-设备检查分析",
          updated_at: "2026-05-23T10:00:00Z",
          agent_name: "ai-report--custom",
        },
        {
          thread_id: "thread-report-bbb",
          title: "周报-油液分析",
          updated_at: "2026-05-22T08:00:00Z",
          agent_name: "ai-report--custom",
        },
      ],
    });

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");

    // "报告历史" link should be visible in the sidebar
    const reportHistoryLink = sidebar.locator("a[href='/workspace/report-runs']");
    await expect(reportHistoryLink).toBeVisible({ timeout: 15_000 });

    // Click the collapsible trigger to expand
    const trigger = sidebar.getByText("报告历史");
    await trigger.click();

    // Thread titles should appear in the expanded sub-list
    await expect(sidebar.getByText("日报-设备检查分析")).toBeVisible({ timeout: 5_000 });
    await expect(sidebar.getByText("周报-油液分析")).toBeVisible({ timeout: 5_000 });

    // "查看全部" link should be visible at the bottom of sub-list
    await expect(sidebar.getByText("查看全部")).toBeVisible({ timeout: 5_000 });
  });

  test("report history nav item without report threads shows plain link", async ({ page }) => {
    mockLangGraphAPI(page, {
      agents: [
        {
          name: "main-agent",
          description: "主智能体",
          display_name: "主智能体",
          icon: null,
          model: null,
          tool_groups: null,
          skills: null,
          mcp_servers: null,
          tags: null,
          source: "builtin",
          editable: false,
          enabled: true,
          nav_items: [
            { path: "/workspace/report-runs", label: "报告历史", icon: "History" },
          ],
        },
      ],
      threads: [],
    });

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");

    // "报告历史" link should be visible as a plain link (no collapsible)
    const reportHistoryLink = sidebar.locator("a[href='/workspace/report-runs']");
    await expect(reportHistoryLink).toBeVisible({ timeout: 15_000 });

    // No sub-list items should be present
    await expect(sidebar.getByText("查看全部")).not.toBeVisible({ timeout: 3_000 });
  });
});

import { expect, test } from "@playwright/test";

import { handleRunStream, mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

test.describe("Personal Assistant UX", () => {
  test.describe("Assistant Avatar (8.4)", () => {
    test("assistant messages show avatar and name label", async ({ page }) => {
      const agents = [
        {
          name: "test-agent",
          description: "Test Agent",
          display_name: "TestBot",
          icon: "🤖",
        },
      ];

      mockLangGraphAPI(page, {
        threads: [
          {
            thread_id: MOCK_THREAD_ID,
            title: "Avatar Test Thread",
            agent_name: "test-agent",
          },
        ],
        agents,
      });

      await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);

      await expect(page.getByText("TestBot")).toBeVisible({ timeout: 10_000 });
    });

    test("assistant messages show default avatar when no agent configured", async ({
      page,
    }) => {
      mockLangGraphAPI(page, {
        threads: [
          {
            thread_id: MOCK_THREAD_ID,
            title: "Default Avatar Thread",
          },
        ],
      });

      await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);

      await expect(page.getByText("Response in thread")).toBeVisible({
        timeout: 10_000,
      });
    });
  });

  test.describe("Greeting Card (3.8)", () => {
    test("new thread shows greeting card with suggestions", async ({ page }) => {
      mockLangGraphAPI(page);

      await page.route("**/api/threads/*/greeting", (route) => {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            greeting: "你好！今天想分析什么设备数据？",
            suggestions: [
              "查看关键设备状态",
              "生成今日巡检报告",
              "分析异常趋势",
            ],
            language: "zh-CN",
          }),
        });
      });

      await page.goto("/workspace/chats/new");

      await expect(
        page.getByText("你好！今天想分析什么设备数据？"),
      ).toBeVisible({ timeout: 10_000 });

      await expect(
        page.getByRole("button", { name: "查看关键设备状态" }),
      ).toBeVisible({ timeout: 5_000 });

      await expect(
        page.getByRole("button", { name: "生成今日巡检报告" }),
      ).toBeVisible();

      await expect(
        page.getByRole("button", { name: "分析异常趋势" }),
      ).toBeVisible();
    });

    test("greeting card shows English suggestions for en-US", async ({
      page,
    }) => {
      mockLangGraphAPI(page);

      await page.route("**/api/threads/*/greeting", (route) => {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            greeting: "Good morning! What equipment would you like to check?",
            suggestions: [
              "Check critical equipment status",
              "Generate today's report",
            ],
            language: "en-US",
          }),
        });
      });

      await page.goto("/workspace/chats/new");

      await expect(
        page.getByText("Good morning! What equipment would you like to check?"),
      ).toBeVisible({ timeout: 10_000 });

      await expect(
        page.getByRole("button", { name: "Check critical equipment status" }),
      ).toBeVisible({ timeout: 5_000 });
    });

    test("clicking suggestion chip sends it as a message", async ({ page }) => {
      let streamCalled = false;
      await page.route("**/runs/stream", (route) => {
        streamCalled = true;
        return handleRunStream(route);
      });

      mockLangGraphAPI(page);

      await page.route("**/api/threads/*/greeting", (route) => {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            greeting: "你好！",
            suggestions: ["查看设备状态"],
            language: "zh-CN",
          }),
        });
      });

      await page.goto("/workspace/chats/new");

      const suggestionButton = page.getByRole("button", {
        name: "查看设备状态",
      });
      await expect(suggestionButton).toBeVisible({ timeout: 10_000 });

      await suggestionButton.click();

      await expect.poll(() => streamCalled, { timeout: 10_000 }).toBeTruthy();
    });
  });
});

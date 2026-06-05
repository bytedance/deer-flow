import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

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
    test("new thread shows greeting card without suggestion chips", async ({
      page,
    }) => {
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
      ).toHaveCount(0);
      await expect(
        page.getByRole("button", { name: "生成今日巡检报告" }),
      ).toHaveCount(0);
      await expect(
        page.getByRole("button", { name: "分析异常趋势" }),
      ).toHaveCount(0);
      await expect(page.getByRole("button", { name: "趋势" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "诊断" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "频谱" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "日报" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "创建" })).toHaveCount(0);
    });

    test("greeting card hides English suggestion chips for en-US", async ({
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
      ).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Trend" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Diagnose" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Spectrum" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Daily Report" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Create" })).toHaveCount(0);
    });

    test("greeting suggestions returned by the API stay hidden", async ({
      page,
    }) => {
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

      await expect(
        page.getByRole("button", { name: "查看设备状态" }),
      ).toHaveCount(0);
      await expect(page.getByRole("button", { name: "趋势" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "诊断" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "频谱" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "日报" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "创建" })).toHaveCount(0);
      await expect(page.getByRole("textbox")).toBeVisible({ timeout: 10_000 });
    });
  });
});

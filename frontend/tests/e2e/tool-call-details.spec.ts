import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const threadId = "00000000-0000-0000-0000-000000004389";

for (const debug of [false, true]) {
  test(`generic tool details with Debug ${debug ? "enabled" : "disabled"}`, async ({
    page,
  }) => {
    await page.addInitScript((enabled) => {
      localStorage.setItem(
        "deerflow.local-settings",
        JSON.stringify({
          tokenUsage: {
            headerTotal: true,
            inlineMode: enabled ? "step_debug" : "per_turn",
          },
        }),
      );
    }, debug);
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: threadId,
          title: "Tool details",
          messages: [
            { type: "human", id: "human", content: "Look up the run" },
            {
              type: "ai",
              id: "ai-tool",
              content: "",
              tool_calls: [
                {
                  id: "call-4389",
                  name: "mcp_lookup",
                  args: { run_id: "run-4389" },
                },
              ],
            },
            {
              type: "tool",
              id: "tool-result",
              tool_call_id: "call-4389",
              status: "error",
              content: "denied: " + "x".repeat(20000),
            },
            { type: "ai", id: "answer", content: "The lookup failed." },
          ],
        },
      ],
    });
    // 默认 mock 关闭了 Token Usage；这里启用入口，但不提供任何调用统计。
    await page.route("**/api/models", (route) =>
      route.fulfill({ json: { models: [], token_usage: { enabled: true } } }),
    );
    await page.goto(`/workspace/chats/${threadId}`);
    await expect(
      page.getByText("The lookup failed.", { exact: true }),
    ).toBeVisible();
    const trigger = page.getByRole("button", {
      name: "Tool details: mcp_lookup (call-4389)",
      exact: true,
    });
    if (!debug) {
      await expect(trigger).toHaveCount(0);
      return;
    }
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(
      page.getByRole("region", { name: "Input", exact: true }),
    ).toHaveCount(0);
    await trigger.click();
    await expect(
      page.getByRole("region", { name: "Input", exact: true }),
    ).toContainText("run-4389");
    await expect(
      page.getByRole("region", { name: "Call ID", exact: true }),
    ).toContainText("call-4389");
    const error = page.getByRole("region", { name: "Error", exact: true });
    await expect(error).toContainText("denied:");
    await expect(error).toContainText("Preview truncated");
    expect(
      (await error.locator("pre").textContent())?.length,
    ).toBeLessThanOrEqual(12000);
    await page.screenshot({
      path: test.info().outputPath("tool-details.png"),
      fullPage: true,
    });
    await trigger.click();
    await expect(error).toHaveCount(0);
  });
}

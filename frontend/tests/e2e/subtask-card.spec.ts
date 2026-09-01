import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

const STOPPED_TASK_PROMPT =
  "Investigate why the stopped subtask card should not remain running after reload.";
const LONG_TASK_PROMPT =
  "你的任务：分析 bytedance/deer-flow 前端核心线程同步文件 `frontend/src/core/threads/hooks.ts`（约 108KB），提取其消息流同步机制的关键信息。背景：用户在 DeerFlow 前端发现子代理任务卡片标题过长，需要确认截断行为。请重点关注消息合并、流式节流与本地排序逻辑，并输出结构化结论。";

const stoppedSubtaskMessages = [
  {
    type: "human",
    id: "msg-human-stopped-subtask",
    content: [
      {
        type: "text",
        text: "Start a subtask and then stop before the task tool returns.",
      },
    ],
  },
  {
    type: "ai",
    id: "msg-ai-stopped-subtask",
    content: "",
    additional_kwargs: {},
    response_metadata: {},
    tool_calls: [
      {
        id: "call-stopped-subtask",
        name: "task",
        args: {
          subagent_type: "general-purpose",
          prompt: STOPPED_TASK_PROMPT,
        },
        type: "tool_call",
      },
    ],
    invalid_tool_calls: [],
  },
];

test.describe("Subtask card", () => {
  test("shows failed after a stopped task thread is reloaded", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Stopped subtask",
          updated_at: "2026-06-18T12:00:00Z",
          messages: stoppedSubtaskMessages,
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await page.reload();

    await expect(page.getByText(STOPPED_TASK_PROMPT)).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("Subtask failed")).toBeVisible();
    await expect(page.getByText("Running subtask")).toHaveCount(0);
  });
  test("truncates a long task title to a single line", async ({ page }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Long subtask title",
          updated_at: "2026-06-18T12:00:00Z",
          messages: [
            stoppedSubtaskMessages[0],
            {
              ...stoppedSubtaskMessages[1],
              id: "msg-ai-long-subtask",
              tool_calls: [
                {
                  id: "call-long-subtask",
                  name: "task",
                  args: {
                    subagent_type: "general-purpose",
                    prompt: LONG_TASK_PROMPT,
                  },
                  type: "tool_call",
                },
              ],
            },
          ],
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await page.reload();

    const title = page.getByTitle(LONG_TASK_PROMPT, { exact: true });
    await expect(title).toBeVisible({ timeout: 15_000 });
    await expect(title).toHaveClass(/truncate/);

    const metrics = await title.evaluate((el) => {
      const style = getComputedStyle(el);
      return {
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
        height: el.getBoundingClientRect().height,
        lineHeight: parseFloat(style.lineHeight),
      };
    });
    expect(metrics.scrollWidth).toBeGreaterThan(metrics.clientWidth);
    expect(metrics.height).toBeLessThanOrEqual(metrics.lineHeight * 1.5);
  });
});

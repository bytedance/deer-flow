import { createServer } from "node:http";
import type { AddressInfo } from "node:net";

import { expect, test, type Locator } from "@playwright/test";

import {
  mockLangGraphAPI,
  MOCK_RUN_ID,
  MOCK_THREAD_ID,
} from "./utils/mock-api";

const STOPPED_TASK_PROMPT =
  "Investigate why the stopped subtask card should not remain running after reload.";
const LONG_TASK_PROMPT =
  "你的任务：分析 bytedance/deer-flow 前端核心线程同步文件 `frontend/src/core/threads/hooks.ts`（约 108KB），提取其消息流同步机制的关键信息。背景：用户在 DeerFlow 前端发现子代理任务卡片标题过长，需要确认截断行为。请重点关注消息合并、流式节流与本地排序逻辑，并输出结构化结论。";
const LONG_RUNNING_STATUS =
  "Writing the quarterly infrastructure cost breakdown report to workspace/reports/q3-infra-cost-breakdown-final-v2.md";
const LONG_TASK_USER_TEXT =
  "Analyze the thread sync hooks and report how the subtask card renders.";

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

const longSubtaskThread = {
  thread_id: MOCK_THREAD_ID,
  title: "Long subtask title",
  updated_at: "2026-06-18T12:00:00Z",
  messages: [
    {
      // Reuse the stopped test's message *shape* only: its human text narrates
      // the stop scenario, which none of the long-title tests exercise.
      ...stoppedSubtaskMessages[0],
      id: "msg-human-long-subtask",
      content: [{ type: "text", text: LONG_TASK_USER_TEXT }],
    },
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
};

async function expectSingleLineEllipsis(title: Locator) {
  await expect(title).toHaveClass(/truncate/);

  const metrics = await title.evaluate((el) => ({
    scrollWidth: el.scrollWidth,
    clientWidth: el.clientWidth,
    height: el.getBoundingClientRect().height,
  }));
  expect(metrics.scrollWidth).toBeGreaterThan(metrics.clientWidth);
  // A pixel budget instead of `parseFloat(lineHeight)`: the `normal` keyword
  // parses to NaN and fails with an opaque "Received NaN" rather than pointing
  // at the layout. One line of `text-sm` is 20px; 32px leaves slack without
  // admitting a wrapped second line.
  expect(metrics.height).toBeLessThanOrEqual(32);
}

/**
 * SSE server that emits one `values` frame carrying an unresolved `task` tool
 * call and then holds the connection open, keeping `thread.isLoading` true so
 * the subtask card renders its running (shimmer) branch. Closed via
 * `closeAllConnections` in test teardown.
 */
async function startRunningSubtaskStream() {
  const aiMessage = {
    type: "ai",
    id: "msg-ai-running-subtask",
    content: "",
    additional_kwargs: {},
    response_metadata: {},
    tool_calls: [
      {
        id: "call-running-subtask",
        name: "task",
        args: {
          subagent_type: "general-purpose",
          prompt: LONG_TASK_PROMPT,
        },
        type: "tool_call",
      },
    ],
    invalid_tool_calls: [],
  };
  const server = createServer((request, response) => {
    let body = "";
    request.on("data", (chunk: Buffer) => {
      body += chunk.toString();
    });
    request.on("end", () => {
      let inputMessages: unknown[] = [];
      let bodyThreadId: string | undefined;
      try {
        const parsed = JSON.parse(body) as {
          input?: { messages?: unknown[] };
          thread_id?: string;
        };
        inputMessages = parsed.input?.messages ?? [];
        bodyThreadId = parsed.thread_id;
      } catch {
        inputMessages = [];
      }
      const threadId =
        /\/threads\/([^/]+)\/runs\/stream/.exec(request.url ?? "")?.[1] ??
        bodyThreadId ??
        MOCK_THREAD_ID;
      const frames = [
        {
          event: "metadata",
          data: { run_id: MOCK_RUN_ID, thread_id: threadId },
        },
        {
          event: "values",
          data: { messages: [...inputMessages, aiMessage] },
        },
        {
          // A `task_running` step whose last tool call carries a long
          // description: the collapsed header's status pill renders it via
          // `explainLastToolCall`, growing the right-hand cluster past the
          // width of a narrow card.
          event: "custom",
          data: {
            type: "task_running",
            task_id: "call-running-subtask",
            message: {
              type: "ai",
              id: "msg-ai-running-subtask-step",
              content: "",
              additional_kwargs: {},
              response_metadata: {},
              tool_calls: [
                {
                  id: "call-running-subtask-step",
                  name: "write_file",
                  args: { description: LONG_RUNNING_STATUS },
                  type: "tool_call",
                },
              ],
              invalid_tool_calls: [],
            },
            message_index: 1,
          },
        },
      ]
        .map(
          (event) =>
            `event: ${event.event}\ndata: ${JSON.stringify(event.data)}\n\n`,
        )
        .join("");
      response.writeHead(200, {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-cache",
        "Content-Type": "text/event-stream",
      });
      response.write(frames);
    });
  });

  await new Promise<void>((resolve, reject) => {
    const handleError = (error: Error) => reject(error);
    server.once("error", handleError);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", handleError);
      resolve();
    });
  });

  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}/runs/stream`,
    async close() {
      server.closeAllConnections();
      await new Promise<void>((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      });
    },
  };
}

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
      threads: [longSubtaskThread],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await page.reload();

    const title = page.getByTitle(LONG_TASK_PROMPT, { exact: true });
    await expect(title).toBeVisible({ timeout: 15_000 });
    await expectSingleLineEllipsis(title);
  });
  test("keeps the header inside the card on a 375px viewport", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    mockLangGraphAPI(page, {
      threads: [longSubtaskThread],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await page.reload();

    const title = page.getByTitle(LONG_TASK_PROMPT, { exact: true });
    await expect(title).toBeVisible({ timeout: 15_000 });

    // The status cluster is shrinkable (`min-w-0`, per-item `truncate`), so a
    // narrow card ellipsizes the cluster instead of collapsing the title to
    // zero width and overflowing the row.
    const row = title.locator(
      "xpath=ancestor::div[contains(@class,'justify-between')][1]",
    );
    const rowMetrics = await row.evaluate((el) => ({
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
    }));
    expect(rowMetrics.scrollWidth).toBeLessThanOrEqual(rowMetrics.clientWidth);
    await expectSingleLineEllipsis(title);
  });
  test("truncates a running task title with the shimmer inline", async ({
    page,
  }) => {
    const streamServer = await startRunningSubtaskStream();
    mockLangGraphAPI(page, {
      runStreamHandler: (route) => route.continue({ url: streamServer.url }),
    });

    try {
      await page.goto("/workspace/chats/new");
      const textarea = page.getByPlaceholder(/how can i assist you/i);
      await expect(textarea).toBeVisible({ timeout: 15_000 });
      await textarea.fill("Run a subtask with a long title");
      await textarea.press("Enter");

      const title = page.getByTitle(LONG_TASK_PROMPT, { exact: true });
      await expect(title).toBeVisible({ timeout: 15_000 });

      // The shimmer must stay one inline text run inside the truncating span:
      // `as="span"` avoids nesting the component's default <p>, and
      // `className="inline"` overrides its `inline-block` so the parent span's
      // nowrap/ellipsis still apply.
      const shimmer = title.locator("span").first();
      await expect(shimmer).toHaveCSS("display", "inline");
      await expectSingleLineEllipsis(title);
    } finally {
      await streamServer.close();
    }
  });
  test("keeps a running card inside the row on a 375px viewport", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    const streamServer = await startRunningSubtaskStream();
    mockLangGraphAPI(page, {
      runStreamHandler: (route) => route.continue({ url: streamServer.url }),
    });

    try {
      await page.goto("/workspace/chats/new");
      const textarea = page.getByPlaceholder(/how can i assist you/i);
      await expect(textarea).toBeVisible({ timeout: 15_000 });
      await textarea.fill("Run a subtask with a long status");
      await textarea.press("Enter");

      // The long `task_running` status pushes the right-hand cluster's
      // max-content past the card width. The cluster must absorb that by
      // ellipsizing (`min-w-0` on both wrappers + per-item `truncate`), not by
      // pinning its width with `shrink-0` and overflowing the row; the title's
      // `min-w-24` floor keeps it visible instead of collapsing to zero.
      const status = page.getByText(LONG_RUNNING_STATUS, { exact: true });
      await expect(status).toBeVisible({ timeout: 15_000 });
      const title = page.getByTitle(LONG_TASK_PROMPT, { exact: true });
      await expect(title).toBeVisible({ timeout: 15_000 });
      await expectSingleLineEllipsis(title);
      const pill = status.locator("xpath=..");
      const row = status.locator(
        "xpath=ancestor::div[contains(@class,'justify-between')][1]",
      );
      const metrics = await row.evaluate((el) => ({
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
      }));
      expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);

      const pillMetrics = await pill.evaluate((el) => ({
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
      }));
      expect(pillMetrics.scrollWidth).toBeGreaterThan(pillMetrics.clientWidth);
    } finally {
      await streamServer.close();
    }
  });
});

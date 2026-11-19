import { createServer } from "node:http";
import type { AddressInfo } from "node:net";

import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const threadId = "00000000-0000-0000-0000-000000004389";

for (const { debug, content, status, label } of [
  {
    debug: false,
    content: "denied: " + "x".repeat(20000),
    status: "error",
    label: "Debug disabled",
  },
  {
    debug: true,
    content: "denied: " + "x".repeat(20000),
    status: "error",
    label: "bounded error",
  },
  {
    debug: true,
    content: '{"run_id":9223372036854775807,"ratio":0.1234567890123456789}',
    status: "success",
    label: "nested numeric precision",
  },
  {
    debug: true,
    content: "9223372036854775807",
    status: "success",
    label: "top-level numeric precision",
  },
] as const) {
  test(`generic tool details: ${label}`, async ({ page }) => {
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
              status,
              content,
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
    const error = page.getByRole("region", {
      name: status === "error" ? "Error" : "Result",
      exact: true,
    });
    if (status === "success") {
      expect(await error.locator("pre").textContent()).toBe(content);
      await expect(
        error.getByText("Preview truncated", { exact: false }),
      ).toHaveCount(0);
      await page
        .context()
        .grantPermissions(["clipboard-read", "clipboard-write"]);
      await error
        .getByRole("button", { name: "Copy to clipboard: Result", exact: true })
        .click();
      await expect
        .poll(() => page.evaluate(() => navigator.clipboard.readText()))
        .toBe(content);
      return;
    }
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

for (const locale of ["en-US", "zh-CN"] as const) {
  test(`tool failures and confirmed scheduler labels (${locale})`, async ({
    page,
    baseURL,
  }) => {
    const zh = locale === "zh-CN";
    const runId = "00000000-0000-0000-0000-000000004390";
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page
      .context()
      .addCookies([{ name: "locale", value: locale, url: baseURL! }]);
    const messages: unknown[] = [
      {
        type: "human",
        id: "human",
        content: zh
          ? "创建定时任务，然后核对输入文件和账户。"
          : "Create a scheduled task, then check the input file and account.",
      },
      {
        type: "ai",
        id: "ai-schedule",
        content: "",
        tool_calls: [
          { id: "schedule", name: "schedule_task", args: { action: "create" } },
        ],
      },
    ];
    const controller = mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: threadId,
          title: zh ? "工具执行反馈" : "Tool execution feedback",
          messages: [messages[0]],
        },
      ],
    });
    await page.route("**/api/models", (route) =>
      route.fulfill({ json: { models: [], token_usage: { enabled: true } } }),
    );
    let finished = false;
    const run = () => ({
      run_id: runId,
      thread_id: threadId,
      assistant_id: "lead_agent",
      status: finished ? "success" : "running",
      metadata: {},
      kwargs: {},
      created_at: "2026-10-25T00:00:00Z",
      updated_at: "2026-10-25T00:00:01Z",
    });
    await page.route(/\/api\/langgraph\/threads\/[^/]+\/runs(\?|$)/, (route) =>
      route.fulfill({ json: [run()] }),
    );
    await page.route(
      `**/api/langgraph/threads/${threadId}/runs/${runId}`,
      (route) => route.fulfill({ json: run() }),
    );
    // Stream actual SSE bytes so the pending assertion runs before any tool receipt.
    let finishStream: (() => void) | undefined;
    const server = createServer((_request, response) => {
      response.writeHead(200, {
        "Access-Control-Allow-Origin": "*",
        "Content-Type": "text/event-stream",
      });
      const frame = (event: string, data: unknown) =>
        `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
      response.write(frame("metadata", { run_id: runId, thread_id: threadId }));
      response.write(frame("values", { messages }));
      finishStream = () =>
        response.end(frame("values", { messages }) + frame("end", {}));
    });
    await new Promise<void>((resolve) =>
      server.listen(0, "127.0.0.1", resolve),
    );
    const { port } = server.address() as AddressInfo;
    await page.route(
      `**/api/langgraph/threads/${threadId}/runs/${runId}/stream*`,
      (route) => route.continue({ url: `http://127.0.0.1:${port}/stream` }),
    );
    try {
      await page.goto(`/workspace/chats/${threadId}`);
      await expect(
        page.getByText(zh ? "定时任务操作" : "Scheduled task operation", {
          exact: true,
        }),
      ).toBeVisible();
      await expect(
        page.getByText(zh ? "已创建定时任务" : "Scheduled a task", {
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        page.getByRole("button", {
          name: zh ? /^工具详情:/ : /^Tool details:/,
        }),
      ).toHaveCount(0);
      await page.screenshot({
        path: test.info().outputPath(`scheduler-pending-${locale}.png`),
        animations: "disabled",
        fullPage: true,
      });
      messages.push({
        type: "tool",
        id: "schedule-result",
        tool_call_id: "schedule",
        content: JSON.stringify({ action: "create" }),
        status: "success",
      });
      for (const [id, name, description, content, status, meta] of [
        [
          "bash-error",
          "bash",
          zh ? "核对输入文件" : "Check input file",
          "File not found",
          "error",
          "error",
        ],
        [
          "mcp-error",
          "mcp_lookup",
          zh ? "查询账户" : "Look up account",
          "Provider denied the request",
          "success",
          "error",
        ],
        [
          "read-ok",
          "read_file",
          zh ? "读取本地记录" : "Read local record",
          '{"error":"ordinary document data"}',
          "success",
          "success",
        ],
      ] as const) {
        messages.push(
          {
            type: "ai",
            id: `ai-${id}`,
            content: "",
            tool_calls: [
              {
                id,
                name,
                args: {
                  description,
                  path: "/mnt/user-data/workspace/input.json",
                },
              },
            ],
          },
          {
            type: "tool",
            id: `result-${id}`,
            tool_call_id: id,
            content,
            status,
            additional_kwargs: { deerflow_tool_meta: { status: meta } },
          },
        );
      }
      messages.push({
        type: "ai",
        id: "answer",
        content: zh
          ? "定时任务已创建，文件和账户核对未成功。"
          : "The scheduled task was created; the file and account checks failed.",
      });
      controller.upsertThread({
        thread_id: threadId,
        title: zh ? "工具执行反馈" : "Tool execution feedback",
        messages,
      });
      finished = true;
      finishStream?.();
      const expandSteps = () =>
        page.getByRole("button", {
          name: zh ? /查看其他.*步骤/ : /more steps/,
        });
      await expandSteps().click();
      await expect(
        page.getByText(zh ? "已创建定时任务" : "Scheduled a task", {
          exact: true,
        }),
      ).toBeVisible();
      await expect(
        page.getByText(zh ? "执行失败" : "Failed", { exact: true }),
      ).toHaveCount(2);
      await expect(
        page.getByRole("button", {
          name: zh ? /^工具详情:/ : /^Tool details:/,
        }),
      ).toHaveCount(0);
      await expect(
        page.getByText(zh ? "结果可能不完整" : "Result may be incomplete", {
          exact: true,
        }),
      ).toHaveCount(0);
      const successfulRead = page.getByText(
        zh ? "读取本地记录" : "Read local record",
        { exact: true },
      );
      await expect(successfulRead).toBeVisible();
      await expect
        .poll(() =>
          successfulRead.evaluate((element) => {
            let opacity = 1;
            for (
              let node: Element | null = element;
              node;
              node = node.parentElement
            ) {
              opacity *= Number(getComputedStyle(node).opacity);
            }
            return opacity;
          }),
        )
        .toBe(1);
      await page.mouse.move(0, 0);
      await page.screenshot({
        path: test.info().outputPath(`normal-errors-${locale}.png`),
        animations: "disabled",
        fullPage: true,
      });
      await page.reload();
      await expandSteps().click();
      await expect(
        page.getByText(zh ? "执行失败" : "Failed", { exact: true }),
      ).toHaveCount(2);
      await page.evaluate(() =>
        localStorage.setItem(
          "deerflow.local-settings",
          JSON.stringify({
            tokenUsage: { headerTotal: true, inlineMode: "step_debug" },
          }),
        ),
      );
      await page.reload();
      await expandSteps().click();
      await expect(
        page.getByRole("button", {
          name: zh ? /^工具详情:/ : /^Tool details:/,
        }),
      ).toHaveCount(2);
      await page
        .getByRole("button", {
          name: `${zh ? "工具详情" : "Tool details"}: mcp_lookup (mcp-error)`,
          exact: true,
        })
        .click();
      await expect(
        page.getByRole("region", { name: zh ? "错误" : "Error", exact: true }),
      ).toContainText("Provider denied the request");
      await expect(
        page.getByRole("region", {
          name: zh ? "调用 ID" : "Call ID",
          exact: true,
        }),
      ).toContainText("mcp-error");
      await page.screenshot({
        path: test.info().outputPath(`existing-debug-${locale}.png`),
        animations: "disabled",
        fullPage: true,
      });
    } finally {
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
}

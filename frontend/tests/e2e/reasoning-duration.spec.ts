import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

const answer = "你好！有什么可以帮你的吗？";
const reasoning = "先理解用户的需求，再给出简洁的回答。";

for (const encoding of ["provider", "inline", "none"] as const) {
  test(`shows one compact Chinese duration header: ${encoding}`, async ({
    page,
  }, testInfo) => {
    await page
      .context()
      .addCookies([
        { name: "locale", value: "zh-CN", url: testInfo.project.use.baseURL! },
      ]);
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "耗时标题预览",
          messages: [
            { type: "human", id: "human-duration", content: "你好" },
            {
              type: "ai",
              id: "ai-duration",
              content:
                encoding === "inline"
                  ? `<think>${reasoning}</think>${answer}`
                  : answer,
              additional_kwargs: {
                turn_duration: 31,
                ...(encoding === "provider"
                  ? { reasoning_content: reasoning }
                  : {}),
              },
            },
          ],
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    const label = page.getByTestId("run-duration");
    await expect(label).toHaveCount(1);
    await expect(label).toHaveText("用时 31 秒");
    await expect(page.getByText(answer, { exact: true })).toBeVisible();
    await expect(page.getByText("本次任务耗时", { exact: false })).toHaveCount(
      0,
    );

    const trigger = page.getByRole("button", {
      name: "用时 31 秒 思考过程",
      exact: true,
    });
    if (encoding !== "none") {
      await expect(trigger).toHaveAttribute("aria-expanded", "false");
      await trigger.click();
      await expect(page.getByText(reasoning, { exact: true })).toBeVisible();
      await trigger.press("Enter");
      await expect(
        page.getByText(reasoning, { exact: true }),
      ).not.toBeVisible();
    } else {
      await expect(trigger).toHaveCount(0);
    }

    const labelBox = await label.boundingBox();
    const answerBox = await page
      .getByText(answer, { exact: true })
      .boundingBox();
    expect(labelBox!.y + labelBox!.height).toBeLessThan(answerBox!.y);
    await page.reload();
    await expect(label).toHaveCount(1);
    await expect(label).toHaveText("用时 31 秒");
    if (encoding !== "none") {
      await expect(trigger).toHaveAttribute("aria-expanded", "false");
    }
    await page.mouse.move(0, 0);
    if (encoding !== "none") {
      // Resolve the theme token in this browser; Chromium versions serialize
      // the same color differently (e.g. oklch vs lab).
      const mutedColor = await trigger.evaluate((element) => {
        const probe = document.createElement("span");
        probe.style.color = "var(--muted-foreground)";
        element.appendChild(probe);
        const color = getComputedStyle(probe).color;
        probe.remove();
        return color;
      });
      await expect(trigger).toHaveCSS("color", mutedColor);
    }
    await page.screenshot({
      animations: "disabled",
      path: testInfo.outputPath(`duration-${encoding}.png`),
    });
  });
}

for (const kind of ["processing", "subagent"] as const) {
  test(`binds completed ${kind} duration to its reasoning disclosure`, async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          messages: [
            {
              type: "human",
              id: "human-duration",
              content: "Think about this",
            },
            {
              type: "ai",
              id: "ai-duration",
              content: "",
              additional_kwargs: {
                reasoning_content: reasoning,
                turn_duration: 31,
              },
              ...(kind === "subagent"
                ? {
                    tool_calls: [
                      {
                        id: "task-duration",
                        name: "task",
                        args: {
                          description: "Research",
                          prompt: "Research",
                          subagent_type: "general-purpose",
                        },
                      },
                    ],
                  }
                : {}),
            },
          ],
        },
      ],
    });
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    const trigger = page.getByRole("button", {
      name: "Took 31s Reasoning",
      exact: true,
    });
    await expect(page.getByTestId("run-duration")).toHaveCount(1);
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await trigger.click();
    await expect(page.getByText(reasoning, { exact: true })).toBeVisible();
    await trigger.press("Enter");
    await expect(page.getByText(reasoning, { exact: true })).not.toBeVisible();
    await expect(
      page.getByRole("button", { name: "Thinking", exact: true }),
    ).toHaveCount(0);
    await page.reload();
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("run-duration")).toHaveCount(1);
  });
}

// Keep the history response pending until the client fallback has painted, then
// release the persisted duration without remounting the chat.
for (const content of [answer, ""]) {
  test(`hands a completed live ${content ? "answer" : "processing"} header from client time to persisted time`, async ({
    page,
  }) => {
    const { createServer } = await import("node:http");
    const runId = "00000000-0000-0000-0000-000000000099";
    const human = {
      type: "human",
      id: "human-live-duration",
      content: "Hello",
    };
    const ai = {
      type: "ai",
      id: "ai-live-duration",
      content,
      run_id: runId,
      additional_kwargs: { reasoning_content: reasoning },
    };
    let complete = false;
    let persistedReady = false;
    let releaseHistory!: () => void;
    const historyReady = new Promise<void>((resolve) => {
      releaseHistory = resolve;
    });
    let finishStream!: () => void;
    const server = createServer((_request, response) => {
      response.writeHead(200, {
        "Access-Control-Allow-Origin": "*",
        "Content-Type": "text/event-stream",
      });
      const frame = (event: string, data: unknown) =>
        response.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
      frame("metadata", { run_id: runId, thread_id: MOCK_THREAD_ID });
      frame("values", { messages: [human, ai] });
      finishStream = () => {
        complete = true;
        frame("end", {});
        response.end();
      };
    });
    await new Promise<void>((resolve) =>
      server.listen(0, "127.0.0.1", resolve),
    );
    const { port } = server.address() as import("node:net").AddressInfo;
    mockLangGraphAPI(page, {
      threads: [{ thread_id: MOCK_THREAD_ID, messages: [] }],
    });
    await page.route("**/api/langgraph/threads/*/runs/stream", (route) =>
      route.continue({ url: `http://127.0.0.1:${port}/stream` }),
    );
    const persisted = [
      human,
      {
        ...ai,
        additional_kwargs: { ...ai.additional_kwargs, turn_duration: 47 },
      },
    ];
    await page.route(/\/api\/threads\/[^/]+\/messages\/page/, async (route) => {
      if (!complete) return route.fallback();
      await historyReady;
      await route.fulfill({
        json: {
          data: persisted.map((content, index) => ({
            run_id: runId,
            seq: index + 1,
            content,
            metadata: { caller: "lead_agent" },
          })),
          has_more: false,
          next_before_seq: null,
        },
      });
    });
    await page.route("**/api/langgraph/threads/*/state", async (route) => {
      if (!complete) return route.fallback();
      await route.fulfill({
        json: {
          values: { messages: persistedReady ? persisted : [human, ai] },
          next: [],
          tasks: [],
        },
      });
    });
    await page.route("**/api/langgraph/threads/*/history", async (route) => {
      if (!complete) return route.fallback();
      await route.fulfill({
        json: [
          {
            values: { messages: persistedReady ? persisted : [human, ai] },
            next: [],
            tasks: [],
            metadata: {},
            created_at: "2026-01-01T00:00:31Z",
            parent_config: null,
          },
        ],
      });
    });
    try {
      const start = new Date("2026-01-01T00:00:00Z");
      await page.clock.setFixedTime(start);
      await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
      const input = page.getByPlaceholder(/how can i assist you/i);
      await input.fill("Hello");
      await input.press("Enter");
      await expect(
        content
          ? page.getByText(answer, { exact: true })
          : page.getByRole("button", { name: "Thinking", exact: true }),
      ).toBeVisible();
      await expect(page.getByTestId("run-duration")).toHaveCount(0);
      await page.clock.setFixedTime(new Date(start.getTime() + 31_000));
      finishStream();
      const clientTrigger = page.getByRole("button", {
        name: "Took 31s Reasoning",
        exact: true,
      });
      await expect(clientTrigger).toBeVisible();
      await expect(page.getByTestId("run-duration")).toHaveCount(1);
      persistedReady = true;
      releaseHistory();
      const persistedTrigger = page.getByRole("button", {
        name: "Took 47s Reasoning",
        exact: true,
      });
      await expect(persistedTrigger).toHaveAttribute("aria-expanded", "false");
      await expect(page.getByTestId("run-duration")).toHaveCount(1);
      await persistedTrigger.click();
      await expect(page.getByText(reasoning, { exact: true })).toBeVisible();
      await page.reload();
      await expect(persistedTrigger).toHaveAttribute("aria-expanded", "false");
      await expect(page.getByTestId("run-duration")).toHaveCount(1);
    } finally {
      releaseHistory();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
}

for (const trailingReasoning of [false, true]) {
  test(`preserves duration ownership around the last tool: trailing reasoning ${trailingReasoning}`, async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          messages: [
            { type: "human", id: "human-tools", content: "Research this" },
            {
              type: "ai",
              id: "ai-earlier",
              run_id: "run-earlier",
              content: "",
              additional_kwargs: {
                reasoning_content: "Earlier reasoning",
                turn_duration: 31,
              },
            },
            {
              type: "ai",
              id: "ai-tool",
              run_id: "run-later",
              content: "",
              tool_calls: [
                {
                  id: "search-duration",
                  name: "web_search",
                  args: { query: "DeerFlow" },
                },
              ],
              additional_kwargs: { turn_duration: 17 },
            },
            {
              type: "tool",
              id: "result-duration",
              run_id: "run-later",
              tool_call_id: "search-duration",
              content: "[]",
            },
            ...(trailingReasoning
              ? [
                  {
                    type: "ai",
                    id: "ai-trailing",
                    run_id: "run-later",
                    content: "",
                    additional_kwargs: {
                      reasoning_content: "Trailing reasoning",
                      turn_duration: 17,
                    },
                  },
                ]
              : []),
          ],
        },
      ],
    });
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByTestId("run-duration")).toHaveCount(2);
    await expect(page.getByTestId("run-duration")).toHaveText([
      "Took 31s",
      "Took 17s",
    ]);
    await expect(
      page.getByRole("button", { name: "Took 31s Reasoning", exact: true }),
    ).toHaveCount(0);
    const trigger = page.getByRole("button", {
      name: "Took 17s Reasoning",
      exact: true,
    });
    if (trailingReasoning) {
      await expect(trigger).toHaveAttribute("aria-expanded", "false");
      await trigger.click();
      await expect(
        page.getByText("Trailing reasoning", { exact: true }),
      ).toBeVisible();
    } else {
      await expect(trigger).toHaveCount(0);
    }
  });
}

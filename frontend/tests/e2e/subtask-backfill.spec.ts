import { createServer, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";

import { expect, test, type Route } from "@playwright/test";

import {
  mockLangGraphAPI,
  MOCK_RUN_ID,
  MOCK_THREAD_ID,
} from "./utils/mock-api";

const TASK_ID = "call-backfill-subtask";
const TASK_PROMPT = "Research the recovered subtask timeline";
const LIVE_SUFFIX = "Complete live reasoning survives the history response.";
const LIVE_TEXT = `${"Live reasoning. ".repeat(600)}${LIVE_SUFFIX}`;
const EARLIER_TEXT = "Earlier reasoning recovered from persisted history.";
const messages = [
  { type: "human", id: "human-backfill", content: "Continue the research" },
  {
    type: "ai",
    id: "ai-backfill",
    run_id: MOCK_RUN_ID,
    content: "",
    tool_calls: [
      {
        id: TASK_ID,
        name: "task",
        args: { subagent_type: "general-purpose", prompt: TASK_PROMPT },
        type: "tool_call",
      },
    ],
  },
];

async function startSubtaskStream() {
  let response: ServerResponse | undefined;
  const send = (event: string, data: unknown) => {
    if (!response) throw new Error("The observer stream has not joined");
    response.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  };
  const server = createServer((_request, stream) => {
    response = stream;
    stream.writeHead(200, {
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "no-cache",
      "Content-Type": "text/event-stream",
    });
    send("metadata", { run_id: MOCK_RUN_ID, thread_id: MOCK_THREAD_ID });
    send("values", { messages });
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return {
    url: `http://127.0.0.1:${(server.address() as AddressInfo).port}/stream`,
    joined: () => response !== undefined,
    send,
    async close() {
      server.closeAllConnections();
      await new Promise<void>((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      });
    },
  };
}

test("late subtask history preserves the full live step at the same index", async ({
  page,
}) => {
  const stream = await startSubtaskStream();
  let historyRequest: Route | undefined;
  const run = {
    run_id: MOCK_RUN_ID,
    thread_id: MOCK_THREAD_ID,
    assistant_id: "lead_agent",
    status: "running",
    metadata: {},
    kwargs: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
  mockLangGraphAPI(page, {
    threads: [
      { thread_id: MOCK_THREAD_ID, title: "Subtask backfill", messages },
    ],
  });
  await page.route(
    new RegExp(`/api/langgraph/threads/${MOCK_THREAD_ID}/runs(?:\\?|$)`),
    (route) => route.fulfill({ json: [run] }),
  );
  await page.route(
    new RegExp(
      `/api/langgraph/threads/${MOCK_THREAD_ID}/runs/${MOCK_RUN_ID}(?:\\?|$)`,
    ),
    (route) => route.fulfill({ json: run }),
  );
  await page.route(
    `**/api/langgraph/threads/${MOCK_THREAD_ID}/runs/${MOCK_RUN_ID}/stream*`,
    (route) => route.continue({ url: stream.url }),
  );
  await page.route(
    `**/api/threads/${MOCK_THREAD_ID}/runs/${MOCK_RUN_ID}/events*`,
    (route) => {
      historyRequest = route;
    },
  );

  try {
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect.poll(stream.joined).toBe(true);
    await page.getByRole("button", { name: new RegExp(TASK_PROMPT) }).click();
    await expect.poll(() => historyRequest !== undefined).toBe(true);
    const query = new URL(historyRequest!.request().url()).searchParams;
    expect(query.get("task_id")).toBe(TASK_ID);
    expect(query.get("event_types")).toBe("subagent.step");

    stream.send("custom", {
      type: "task_running",
      task_id: TASK_ID,
      message_index: 2,
      message: { type: "ai", id: "subtask-live", content: LIVE_TEXT },
    });
    // The card clamps long reasoning visually. Check its rendered text so
    // truncation by the history payload cannot hide behind the layout clamp.
    const fullStep = page.getByText(LIVE_TEXT, { exact: true });
    await expect(fullStep).toHaveCount(1);

    await historyRequest!.fulfill({
      json: [
        { seq: 1, text: EARLIER_TEXT, truncated: false },
        { seq: 2, text: LIVE_TEXT.slice(0, 8192), truncated: true },
      ].map(({ seq, text, truncated }) => ({
        seq,
        event_type: "subagent.step",
        content: {
          task_id: TASK_ID,
          message_index: seq,
          kind: "ai",
          text,
          truncated,
        },
      })),
    });
    historyRequest = undefined;
    // The newly recovered earlier step proves the response has been applied.
    await expect(page.getByText(EARLIER_TEXT, { exact: true })).toHaveCount(1);
    await expect(fullStep).toHaveCount(1);
    await expect(
      page.getByText(LIVE_TEXT.slice(0, 8192), { exact: true }),
    ).toHaveCount(0);
  } finally {
    await historyRequest?.abort();
    await stream.close();
  }
});

import { createServer } from "node:http";
import type { AddressInfo } from "node:net";

import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const THREAD_ID = "00000000-0000-0000-0000-000000004354";
const RUN_ID = "00000000-0000-0000-0000-000000004355";
const MISSING_PATH_THREAD_ID = "00000000-0000-0000-0000-000000004356";
const ARTIFACT_PATH = "/artifact-fixtures/batched-report.md";

const INITIAL_MESSAGES = [
  {
    type: "human",
    id: "msg-human-batched-artifact",
    content: [{ type: "text", text: "Create a batched markdown report" }],
  },
];

function batchedWriteFileStreamFrames() {
  const chunks = [
    {
      content: "",
      additional_kwargs: {},
      response_metadata: {},
      type: "AIMessageChunk",
      name: null,
      id: "msg-ai-batched-artifact",
      tool_calls: [
        {
          name: "write_file",
          args: { path: ARTIFACT_PATH, content: "Hello " },
          id: "call-batched-artifact",
          type: "tool_call",
        },
      ],
      invalid_tool_calls: [],
      usage_metadata: null,
      tool_call_chunks: [
        {
          name: "write_file",
          args: `{"path":"${ARTIFACT_PATH}","content":"Hello `,
          id: "call-batched-artifact",
          index: 0,
          type: "tool_call_chunk",
        },
      ],
      chunk_position: null,
    },
    {
      content: "",
      additional_kwargs: {},
      response_metadata: {},
      type: "AIMessageChunk",
      name: null,
      id: "msg-ai-batched-artifact",
      tool_calls: [],
      invalid_tool_calls: [
        {
          name: null,
          args: 'world"}',
          id: null,
          error: null,
          type: "invalid_tool_call",
        },
      ],
      usage_metadata: null,
      tool_call_chunks: [
        {
          name: null,
          args: 'world"}',
          id: null,
          index: 0,
          type: "tool_call_chunk",
        },
      ],
      chunk_position: null,
    },
  ];
  const events = [
    {
      event: "metadata",
      data: { run_id: RUN_ID, thread_id: THREAD_ID },
    },
    {
      event: "values",
      data: {
        messages: [
          ...INITIAL_MESSAGES,
          {
            type: "human",
            id: "msg-human-batched-artifact-follow-up",
            content: [{ type: "text", text: "Continue the report" }],
          },
        ],
      },
    },
    ...chunks.map((chunk) => ({ event: "messages", data: [chunk, {}] })),
  ];

  return events.map(
    (event) => `event: ${event.event}\ndata: ${JSON.stringify(event.data)}\n\n`,
  );
}

async function startBatchedWriteFileStreamServer() {
  const frames = batchedWriteFileStreamFrames();
  const server = createServer((_request, response) => {
    response.writeHead(200, {
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "no-cache",
      "Content-Type": "text/event-stream",
    });
    response.write(frames.slice(0, 3).join(""));

    const nextBatch = setTimeout(() => {
      response.write(frames[3]);
    }, 300);
    const finishStream = setTimeout(() => {
      response.end();
    }, 2_000);
    response.once("close", () => {
      clearTimeout(nextBatch);
      clearTimeout(finishStream);
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

test("assembles streamed write-file argument deltas in the artifact preview", async ({
  page,
}) => {
  let streamStarted = false;
  let releasePostStreamHistory!: () => void;
  const postStreamHistoryReleased = new Promise<void>((resolve) => {
    releasePostStreamHistory = resolve;
  });
  const streamServer = await startBatchedWriteFileStreamServer();
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: THREAD_ID,
        title: "Batched artifact streaming",
        messages: INITIAL_MESSAGES,
      },
    ],
  });
  await page.route("**/api/langgraph/threads/*/history", async (route) => {
    if (streamStarted) {
      await postStreamHistoryReleased;
    }
    return route.fallback();
  });
  await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
    streamStarted = true;
    return route.continue({ url: streamServer.url });
  });

  try {
    await page.goto(`/workspace/chats/${THREAD_ID}`);

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill("Continue the report");
    await textarea.press("Enter");

    await expect(page.getByText(ARTIFACT_PATH)).toBeVisible({
      timeout: 10_000,
    });

    const artifactsPanel = page.locator("#artifacts");
    await expect(artifactsPanel).toBeVisible();
    await expect(artifactsPanel.getByText("batched-report.md")).toBeVisible();
    await expect(artifactsPanel.getByText("Hello world")).toBeVisible();
  } finally {
    releasePostStreamHistory();
    await streamServer.close();
  }
});

test("does not open an artifact for a file tool call without a path", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: MISSING_PATH_THREAD_ID,
        title: "File tool without a path",
        messages: [
          ...INITIAL_MESSAGES,
          {
            type: "ai",
            id: "msg-ai-missing-path",
            content: "",
            tool_calls: [
              {
                id: "call-missing-path",
                name: "write_file",
                args: { description: "Write file" },
              },
            ],
          },
        ],
      },
    ],
  });

  await page.goto(`/workspace/chats/${MISSING_PATH_THREAD_ID}`);

  const writeFileStep = page.getByText("Write file", { exact: true });
  await expect(writeFileStep).toBeVisible({ timeout: 15_000 });
  await writeFileStep.click();
  await expect(page.locator("#artifacts")).toBeHidden();
});

import { createServer } from "node:http";
import type { AddressInfo } from "node:net";

import { expect, test, type Locator } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const STREAMING_THREAD_ID = "00000000-0000-0000-0000-000000004576";
const SETTLED_THREAD_ID = "00000000-0000-0000-0000-000000004577";
const RUN_ID = "00000000-0000-0000-0000-000000004578";

const REASONING_TEXT =
  "The user asked who I am, so I will list the core capabilities.";
const ANSWER_TEXT = "I am DeerFlow, an open-source super agent.";

const INITIAL_MESSAGES = [
  {
    type: "human",
    id: "msg-human-4576",
    content: [{ type: "text", text: "Who are you?" }],
  },
];

const SETTLED_AI_MESSAGE = {
  type: "ai",
  id: "msg-ai-4576-settled",
  content: ANSWER_TEXT,
  additional_kwargs: { reasoning_content: REASONING_TEXT },
};

/**
 * One AI chunk carrying both reasoning and answer text, which is the state the
 * bubble is in while a reasoning model streams its answer.
 */
function reasoningStreamFrames() {
  const events = [
    {
      event: "metadata",
      data: { run_id: RUN_ID, thread_id: STREAMING_THREAD_ID },
    },
    {
      event: "values",
      data: {
        messages: [
          ...INITIAL_MESSAGES,
          {
            type: "human",
            id: "msg-human-4576-follow-up",
            content: [{ type: "text", text: "Summarize that briefly" }],
          },
        ],
      },
    },
    {
      event: "messages",
      data: [
        {
          content: ANSWER_TEXT,
          additional_kwargs: { reasoning_content: REASONING_TEXT },
          response_metadata: {},
          type: "AIMessageChunk",
          name: null,
          id: "msg-ai-4576-streaming",
          tool_calls: [],
          invalid_tool_calls: [],
          usage_metadata: null,
          tool_call_chunks: [],
          chunk_position: null,
        },
        {},
      ],
    },
  ];

  return events.map(
    (event) => `event: ${event.event}\ndata: ${JSON.stringify(event.data)}\n\n`,
  );
}

/** Holds the SSE connection open so the turn stays in its streaming state. */
async function startHeldOpenStreamServer() {
  const frames = reasoningStreamFrames();
  const server = createServer((_request, response) => {
    response.writeHead(200, {
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "no-cache",
      "Content-Type": "text/event-stream",
    });
    response.write(frames.join(""));
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

async function expectRenderedAbove(upper: Locator, lower: Locator) {
  await expect(upper).toBeVisible();
  await expect(lower).toBeVisible();
  const upperBox = await upper.boundingBox();
  const lowerBox = await lower.boundingBox();
  expect(upperBox).not.toBeNull();
  expect(lowerBox).not.toBeNull();
  expect(upperBox!.y).toBeLessThan(lowerBox!.y);
}

test("renders reasoning above the answer text while the turn is streaming", async ({
  page,
}) => {
  const streamServer = await startHeldOpenStreamServer();
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: STREAMING_THREAD_ID,
        title: "Streaming reasoning order",
        messages: INITIAL_MESSAGES,
      },
    ],
  });
  await page.route("**/api/langgraph/threads/*/runs/stream", (route) =>
    route.continue({ url: streamServer.url }),
  );

  try {
    await page.goto(`/workspace/chats/${STREAMING_THREAD_ID}`);

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill("Summarize that briefly");
    await textarea.press("Enter");

    // The streaming turn renders inside the chain-of-thought panel, whose
    // reasoning disclosure is labelled "Thinking".
    await expectRenderedAbove(
      page.getByText("Thinking", { exact: true }),
      page.getByText(ANSWER_TEXT),
    );
  } finally {
    await streamServer.close();
  }
});

test("renders reasoning above the answer text after the turn settles", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: SETTLED_THREAD_ID,
        title: "Settled reasoning order",
        messages: [...INITIAL_MESSAGES, SETTLED_AI_MESSAGE],
      },
    ],
  });

  await page.goto(`/workspace/chats/${SETTLED_THREAD_ID}`);

  // The settled turn renders as an assistant bubble, whose reasoning
  // disclosure is labelled "Reasoning".
  await expectRenderedAbove(
    page.getByText("Reasoning", { exact: true }),
    page.getByText(ANSWER_TEXT),
  );
});
